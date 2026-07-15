#!/usr/bin/env python3
"""Sunrise Alarm - configuration UI.
Set the time / songs / ramp, then Arm (installs the timers + RTC wake) or run a
60-second Test to see the whole sequence immediately.
"""
import gi, os, json, subprocess, threading, datetime
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango

GLib.set_prgname("sunrise-alarm")
DIR = os.path.expanduser("~/.local/share/sunrise-alarm")
CFG_DIR = os.path.expanduser("~/.config/sunrise-alarm")
CFG = os.path.join(CFG_DIR, "config.json")
DEFAULTS = {
    "alarm_time": "07:40", "enabled": True, "repeat_daily": True,
    "calm_uri": "spotify:playlist:6wFWKXnsBFQxWQjSug7ory",
    "wake_uri": "spotify:playlist:37i9dQZF1EQpj7X7UK8OOF",
    "sunrise_min": 20, "top_vol": 0.85, "sink_match": "DL6950",
}

def load():
    try:
        with open(CFG) as f: c = json.load(f)
    except Exception: c = {}
    d = dict(DEFAULTS); d.update(c or {}); return d

def save(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w") as f: json.dump(c, f, indent=2)

class App(Gtk.Window):
    def __init__(self):
        super().__init__(title="Sunrise Alarm")
        self.set_wmclass("sunrise-alarm", "Sunrise Alarm")
        self.set_border_width(16); self.set_default_size(440, 0)
        self.cfg = load()
        g = Gtk.Grid(row_spacing=10, column_spacing=12)
        self.add(g)
        r = 0

        title = Gtk.Label(); title.set_markup("<span size='xx-large' weight='bold'>Sunrise Alarm</span>")
        title.set_halign(Gtk.Align.START); g.attach(title, 0, r, 2, 1); r += 1

        # time
        h, m = self.cfg["alarm_time"].split(":")
        g.attach(self._lbl("Alarm time"), 0, r, 1, 1)
        tbox = Gtk.Box(spacing=6)
        self.hh = Gtk.SpinButton.new_with_range(0, 23, 1); self.hh.set_value(int(h)); self.hh.set_orientation(Gtk.Orientation.VERTICAL)
        self.mm = Gtk.SpinButton.new_with_range(0, 59, 1); self.mm.set_value(int(m)); self.mm.set_orientation(Gtk.Orientation.VERTICAL)
        for s in (self.hh, self.mm): s.set_numeric(True)
        tbox.pack_start(self.hh, False, False, 0)
        tbox.pack_start(Gtk.Label(label=":"), False, False, 0)
        tbox.pack_start(self.mm, False, False, 0)
        g.attach(tbox, 1, r, 1, 1); r += 1

        # enabled + repeat
        g.attach(self._lbl("Enabled"), 0, r, 1, 1)
        self.en = Gtk.Switch(); self.en.set_active(bool(self.cfg["enabled"])); self.en.set_halign(Gtk.Align.START)
        g.attach(self.en, 1, r, 1, 1); r += 1
        g.attach(self._lbl("Repeat daily"), 0, r, 1, 1)
        self.rep = Gtk.Switch(); self.rep.set_active(bool(self.cfg["repeat_daily"])); self.rep.set_halign(Gtk.Align.START)
        g.attach(self.rep, 1, r, 1, 1); r += 1

        # sunrise length
        g.attach(self._lbl("Sunrise length (min)"), 0, r, 1, 1)
        self.dur = Gtk.SpinButton.new_with_range(1, 60, 1); self.dur.set_value(int(self.cfg["sunrise_min"]))
        g.attach(self.dur, 1, r, 1, 1); r += 1

        # top volume
        g.attach(self._lbl("Top volume"), 0, r, 1, 1)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.set_value(round(float(self.cfg["top_vol"]) * 100)); self.vol.set_hexpand(True)
        g.attach(self.vol, 1, r, 1, 1); r += 1

        # URIs
        g.attach(self._lbl("Calm playlist URI"), 0, r, 1, 1)
        self.calm = Gtk.Entry(); self.calm.set_text(self.cfg["calm_uri"]); self.calm.set_hexpand(True)
        g.attach(self.calm, 1, r, 1, 1); r += 1
        g.attach(self._lbl("Wake track URI"), 0, r, 1, 1)
        self.wake = Gtk.Entry(); self.wake.set_text(self.cfg["wake_uri"]); self.wake.set_hexpand(True)
        g.attach(self.wake, 1, r, 1, 1); r += 1

        # buttons
        bbox = Gtk.Box(spacing=8); bbox.set_homogeneous(True)
        self.arm_btn = Gtk.Button(label="Arm"); self.arm_btn.get_style_context().add_class("suggested-action")
        self.arm_btn.connect("clicked", self.on_arm)
        disarm = Gtk.Button(label="Disarm"); disarm.connect("clicked", self.on_disarm)
        test = Gtk.Button(label="Test (60s)"); test.connect("clicked", self.on_test)
        stop = Gtk.Button(label="Stop test"); stop.connect("clicked", self.on_stop)
        for b in (self.arm_btn, disarm, test, stop): bbox.pack_start(b, True, True, 0)
        g.attach(bbox, 0, r, 2, 1); r += 1

        self.status = Gtk.Label(); self.status.set_line_wrap(True); self.status.set_halign(Gtk.Align.START)
        self.status.set_xalign(0); self.status.modify_font(Pango.FontDescription("monospace 9"))
        g.attach(self.status, 0, r, 2, 1); r += 1

        self.connect("destroy", Gtk.main_quit)
        self.refresh_status()
        GLib.timeout_add_seconds(5, self.refresh_status)

    def _lbl(self, t):
        l = Gtk.Label(label=t); l.set_halign(Gtk.Align.START); return l

    def collect(self):
        c = dict(self.cfg)
        c["alarm_time"] = f"{int(self.hh.get_value()):02d}:{int(self.mm.get_value()):02d}"
        c["enabled"] = self.en.get_active()
        c["repeat_daily"] = self.rep.get_active()
        c["sunrise_min"] = int(self.dur.get_value())
        c["top_vol"] = round(self.vol.get_value() / 100.0, 2)
        c["calm_uri"] = self.calm.get_text().strip()
        c["wake_uri"] = self.wake.get_text().strip()
        self.cfg = c; save(c); return c

    def _bg(self, argv, done=None):
        def work():
            try:
                p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                out = (p.stdout or "") + (p.stderr or "")
            except Exception as e:
                out = f"error: {e}"
            GLib.idle_add(self._set_status, out.strip())
            if done: GLib.idle_add(self.refresh_status)
        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, t):
        self.status.set_text(t[-800:]); return False

    def on_arm(self, _):
        c = self.collect()
        self._set_status("Arming... (approve the password prompt for RTC wake)")
        self._bg(["bash", os.path.join(DIR, "schedule.sh"), "arm", c["alarm_time"]], done=True)

    def on_disarm(self, _):
        self._set_status("Disarming...")
        self._bg(["bash", os.path.join(DIR, "schedule.sh"), "disarm"], done=True)

    def on_test(self, _):
        self.collect()
        subprocess.Popen(["setsid", "-f", "python3", os.path.join(DIR, "engine.py"), "test", "60"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._set_status("Test running (60s): watch the screen + listen. Press any key on the sunrise to dismiss.")

    def on_stop(self, _):
        subprocess.run(["pkill", "-f", "engine.py test"], capture_output=True)
        subprocess.run(["pkill", "-f", "sunrise-alarm/fallback.wav"], capture_output=True)
        self._set_status("Test stopped.")

    def refresh_status(self):
        try:
            p = subprocess.run(["systemctl", "--user", "list-timers", "sunrise-alarm.timer", "--no-pager"],
                               capture_output=True, text=True, timeout=6)
            armed = "sunrise-alarm.timer" in p.stdout
            nxt = ""
            for line in p.stdout.splitlines():
                if "sunrise-alarm.timer" in line:
                    nxt = line.strip().split("  ")[0]
            state = f"ARMED  next: {nxt}" if armed else "DISARMED"
        except Exception as e:
            state = f"(status error: {e})"
        self.status.set_text(state)
        return True

win = App(); win.show_all(); Gtk.main()
