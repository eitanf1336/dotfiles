#!/usr/bin/env python3
"""Sunrise Alarm - engine (the actual wake sequence).

Ramps the DisplayLink screens warm->white (GTK window + their brightness overlay)
while a calm Spotify playlist fades up to top volume; at the wake mark it switches
to the wake track and ramps 0->top; then holds (bright + song) until a key/click
dismisses it. Guaranteed-audible: if Spotify won't play, a local fallback tone loops.

Reliability notes baked in:
- Spotify MPRIS is driven with SYNCHRONOUS dbus (--print-reply); fire-and-forget drops.
- Audio sink is pinned to the wired dock by name (ids drift), unmuted, made default.
- Display is force-woken (screensaver off + input nudge + nightlight off).
- Everything is logged to engine.log so a failed run is diagnosable.

Usage: engine.py real | test [seconds]
"""
import gi, subprocess, time, sys, os, json, signal, datetime, re, random, atexit
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

APP_DIR  = os.path.expanduser("~/.local/share/sunrise-alarm")
CFG      = os.path.expanduser("~/.config/sunrise-alarm/config.json")
LOG      = os.path.join(APP_DIR, "engine.log")
FALLBACK = os.path.join(APP_DIR, "fallback.wav")
HOME_BIN = os.path.expanduser("~/.local/bin")
DEST, OBJ, IFACE = "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player"

DEFAULTS = {
    "alarm_time": "07:40", "enabled": True, "repeat_daily": True,
    "calm_uri":  "spotify:playlist:6wFWKXnsBFQxWQjSug7ory",
    "wake_uri":  "spotify:playlist:37i9dQZF1EQpj7X7UK8OOF",
    "sunrise_min": 20, "top_vol": 0.85, "sink_match": "DL6950",
}

def load_cfg():
    try:
        with open(CFG) as f: c = json.load(f)
    except Exception: c = {}
    d = dict(DEFAULTS); d.update(c or {}); return d

def log(m):
    line = f"[{datetime.datetime.now():%F %T}] {m}"
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass
    print(line, flush=True)

def _run(cmd, to=8):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=to)
    except Exception as e:
        log(f"run fail {cmd[:2]}: {e}"); return None

# ---------- Spotify (synchronous dbus) ----------
def sp_ctl(method): _run(["dbus-send","--session","--print-reply","--dest="+DEST,OBJ,IFACE+"."+method])
def sp_open(uri):   _run(["dbus-send","--session","--print-reply","--dest="+DEST,OBJ,IFACE+".OpenUri","string:"+uri])
def sp_shuffle(on):
    _run(["dbus-send","--session","--print-reply","--dest="+DEST,OBJ,
          "org.freedesktop.DBus.Properties.Set","string:"+IFACE,"string:Shuffle",
          "variant:boolean:"+("true" if on else "false")])
def sp_status():
    r = _run(["dbus-send","--session","--print-reply","--dest="+DEST,OBJ,
              "org.freedesktop.DBus.Properties.Get","string:"+IFACE,"string:PlaybackStatus"], 5)
    return "Playing" if (r and "Playing" in r.stdout) else "Paused"
def sp_alive():
    r = _run(["dbus-send","--session","--print-reply","--dest="+DEST,OBJ,
              "org.freedesktop.DBus.Introspectable.Introspect"], 4)
    return bool(r and r.returncode == 0)
def ensure_spotify():
    if sp_alive(): return
    log("spotify not up; launching")
    subprocess.Popen(["setsid","-f","spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(25):
        if sp_alive(): break
        time.sleep(1)
    time.sleep(6)
def play_context(uri):
    sp_ctl("Play"); time.sleep(0.6); sp_open(uri); time.sleep(0.5); sp_ctl("Play")

# ---------- audio sink ----------
SINK = {"id": "@DEFAULT_AUDIO_SINK@"}
def find_sink(match):
    r = _run(["wpctl","status"])
    if not r: return None
    inseg = False
    for line in r.stdout.splitlines():
        if "Sinks:" in line: inseg = True; continue
        if inseg and "Sources:" in line: break
        if inseg and match in line:
            m = re.search(r'(\d+)\.\s', line)
            if m: return m.group(1)
    return None
def prep_audio(cfg):
    sid = find_sink(cfg["sink_match"])
    if sid:
        SINK["id"] = sid
        _run(["wpctl","set-default",sid]); _run(["wpctl","set-mute",sid,"0"])
        log(f"audio sink pinned id={sid} (match {cfg['sink_match']})")
    else:
        log("dock sink not found -> using @DEFAULT_AUDIO_SINK@")
def setvol(v): _run(["wpctl","set-volume",SINK["id"],f"{max(0.0,min(1.0,v)):.3f}"])

# ---------- fallback tone ----------
_fb = {"proc": None}
def fallback_start(loud=True):
    if _fb["proc"] is None and os.path.exists(FALLBACK):
        log("fallback tone: START")
        _fb["proc"] = subprocess.Popen(["bash","-c", f"while true; do pw-play '{FALLBACK}'; done"],
                                       preexec_fn=os.setsid, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def fallback_stop():
    p = _fb["proc"]
    if p:
        try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception: pass
        _fb["proc"] = None

# ---------- display ----------
def _bin(name): return os.path.join(HOME_BIN, name)
def brightness(pct):
    if os.path.exists(_bin("brightness")): _run([_bin("brightness"), str(int(pct))], 5)
def force_display_on():
    _run(["gdbus","call","--session","--dest","org.gnome.ScreenSaver","--object-path",
          "/org/gnome/ScreenSaver","--method","org.gnome.ScreenSaver.SetActive","false"], 5)
    for dx in ("25","-25"):
        _run(["ydotool","mousemove","-x",dx,"-y",dx], 3)
    if os.path.exists(_bin("nightlight")): _run([_bin("nightlight"),"off"], 4)
    log("display force-on issued")
def nudge_display():
    # lightweight input nudge so DisplayLink panels don't re-blank mid-ramp
    for dx in ("10","-10"):
        _run(["ydotool","mousemove","-x",dx,"-y",dx], 3)
def get_idle_delay():
    # gsettings prints e.g. "uint32 600"; take the trailing number, not the 32 in uint32
    r = _run(["gsettings","get","org.gnome.desktop.session","idle-delay"], 4)
    if r and r.stdout and r.stdout.strip():
        tok = r.stdout.strip().split()[-1]
        if tok.isdigit(): return int(tok)
    return None
def set_idle_delay(v):
    _run(["gsettings","set","org.gnome.desktop.session","idle-delay",str(int(v))], 4)
def restore_idle():
    # put the screen-blank timeout back exactly as we found it (idempotent)
    if st["idle_saved"] is not None and not st["idle_restored"]:
        set_idle_delay(st["idle_saved"]); st["idle_restored"] = True
        log(f"idle-delay restored to {st['idle_saved']}")

# ---------- timing ----------
mode = sys.argv[1] if len(sys.argv) > 1 else "real"
cfg = load_cfg()
if mode == "test":
    total = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    WAKE_T, CHILD_RAMP = total * 0.75, total * 0.15
else:
    WAKE_T, CHILD_RAMP = float(cfg["sunrise_min"]) * 60.0, 60.0
TOP = float(cfg["top_vol"]); CALM = cfg["calm_uri"]; WAKE = cfg["wake_uri"]
log(f"ENGINE start mode={mode} WAKE_T={WAKE_T:.0f}s child_ramp={CHILD_RAMP:.0f}s top={TOP} calm={CALM} wake={WAKE}")

# ---------- sequence state ----------
st = {"rgb": (0.05,0.01,0.0), "phase": "calm", "t0": None, "childfull": False,
      "start": time.monotonic(), "done": False, "lastvol": -1.0, "lastbri": -1, "n": 0,
      "calm_ok": False, "wake_ok": False, "idle_saved": None, "idle_restored": False}

KF = [(0.00,(0.05,0.01,0.00)),(0.25,(0.28,0.07,0.02)),(0.50,(0.70,0.30,0.08)),
      (0.72,(1.00,0.62,0.28)),(0.88,(1.00,0.85,0.60)),(1.00,(1.00,0.98,0.95))]
def color_at(p):
    if p >= 1.0: return (1.0,1.0,1.0)
    for i in range(len(KF)-1):
        p0,c0 = KF[i]; p1,c1 = KF[i+1]
        if p0 <= p <= p1:
            f = (p-p0)/(p1-p0) if p1 > p0 else 0
            return tuple(c0[j]+(c1[j]-c0[j])*f for j in range(3))
    return KF[-1][1]
def maybe_setvol(v):
    if abs(v - st["lastvol"]) >= 0.01: setvol(v); st["lastvol"] = v
def maybe_brightness(p):
    pct = int(15 + 85*min(p,1.0))
    if pct - st["lastbri"] >= 5 or (pct >= 100 and st["lastbri"] < 100):
        brightness(pct); st["lastbri"] = pct

def on_draw(w, cr):
    r,g,b = st["rgb"]; cr.set_source_rgb(r,g,b); cr.paint(); return False

def dismiss(*a):
    if st["done"]: return True
    st["done"] = True
    log("DISMISSED by user")
    restore_idle()
    fallback_stop(); sp_ctl("Pause"); setvol(0.35)
    Gtk.main_quit()
    return True

def make_windows():
    d = Gdk.Display.get_default(); wins = []
    for i in range(d.get_n_monitors()):
        geo = d.get_monitor(i).get_geometry()
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False); win.set_keep_above(True); win.set_can_focus(True)
        win.add_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        win.connect("key-press-event", dismiss)
        win.connect("button-press-event", dismiss)
        a = Gtk.DrawingArea(); a.connect("draw", on_draw); win.add(a)
        win.move(geo.x, geo.y); win.set_default_size(geo.width, geo.height)
        win.show_all(); win.fullscreen_on_monitor(win.get_screen(), i)
        wins.append((win, a))
    if wins: wins[0][0].present()
    return wins

def start_calm():
    log("phase CALM: starting playlist")
    play_context(CALM); time.sleep(1.0)
    st["calm_ok"] = (sp_status() == "Playing")
    log(f"calm playing={st['calm_ok']}")
    if not st["calm_ok"]:
        ensure_spotify(); play_context(CALM); time.sleep(1.0)
        st["calm_ok"] = (sp_status() == "Playing")
        log(f"calm retry playing={st['calm_ok']}")

def start_wake():
    log("phase WAKE: switching to wake track")
    setvol(0.0); st["lastvol"] = 0.0
    if WAKE.startswith(("spotify:playlist:", "spotify:album:", "spotify:artist:")):
        # random song from the playlist every morning: shuffle on, then skip a
        # random number of tracks in (works even if the client ignores shuffle).
        sp_shuffle(True); time.sleep(0.2)
        sp_open(WAKE); time.sleep(0.6); sp_ctl("Play"); time.sleep(0.5)
        skips = random.randint(1, 10)
        for _ in range(skips):
            sp_ctl("Next"); time.sleep(0.15)
        sp_ctl("Play"); time.sleep(0.6)
        log(f"wake: shuffled playlist, skipped {skips} tracks in")
    else:
        sp_open(WAKE); time.sleep(0.5); sp_ctl("Play"); time.sleep(0.8)
    st["wake_ok"] = (sp_status() == "Playing")
    log(f"wake playing={st['wake_ok']}")
    if not st["wake_ok"]:
        log("wake track failed -> fallback tone")
        fallback_start()
    st["t0"] = time.monotonic()

# ---------- go ----------
try: subprocess.run(["notify-send","-u","critical","Sunrise Alarm","Good morning"], timeout=4)
except Exception: pass
force_display_on()
st["idle_saved"] = get_idle_delay()
set_idle_delay(0)                       # keep the panels lit for the whole ramp
log(f"idle-delay set to 0 for alarm (was {st['idle_saved']})")
atexit.register(restore_idle)
signal.signal(signal.SIGTERM, lambda *a: (restore_idle(), os._exit(0)))
prep_audio(cfg)
ensure_spotify()
wins = make_windows()
brightness(15); st["lastbri"] = 15
setvol(0.0); st["lastvol"] = 0.0
start_calm()

def tick():
    if st["done"]: return False
    st["n"] += 1
    t = time.monotonic() - st["start"]
    p = min(t/WAKE_T, 1.0)
    st["rgb"] = color_at(p)
    for _,a in wins: a.queue_draw()
    maybe_brightness(p)
    if st["phase"] == "calm":
        if t < WAKE_T:
            maybe_setvol(TOP * (t/WAKE_T))
            if st["n"] % 900 == 0:              # ~every 3 min, keep the panels awake
                nudge_display(); log("display nudge (keep-awake)")
            # calm watchdog: if spotify died and no fallback, start it softly
            if st["n"] % 100 == 0 and not st["calm_ok"] and _fb["proc"] is None:
                if sp_status() != "Playing": fallback_start()
        else:
            st["phase"] = "wake"; brightness(100); start_wake()
    else:
        if not st["childfull"]:
            el = time.monotonic() - st["t0"]
            maybe_setvol(TOP * min(el/CHILD_RAMP, 1.0))
            if el >= CHILD_RAMP: st["childfull"] = True
        else:
            # test mode ends itself after a short hold; real alarm holds until dismissed
            if mode == "test" and (time.monotonic() - st["t0"]) > CHILD_RAMP + 12:
                log("test window complete -> auto-dismiss")
                dismiss(); return False
            if st["n"] % 40 == 0 and _fb["proc"] is None and sp_status() != "Playing":
                # wake watchdog: keep noise alive until dismissed
                sp_open(WAKE); time.sleep(0.3); sp_ctl("Play")
                if sp_status() != "Playing": fallback_start()
    return True   # real mode never auto-quits; only dismiss() ends it

GLib.timeout_add(200, tick)
Gtk.main()
