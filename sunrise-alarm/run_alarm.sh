#!/bin/bash
# Env wrapper the systemd --user timer calls. Fixes up the graphical-session env
# (systemd user units don't always inherit WAYLAND_DISPLAY etc.) then runs the engine.
#
# STALENESS GUARD: an OnCalendar timer whose elapse point passed while the machine
# was suspended fires the instant the lid opens (Persistent=false only suppresses
# catch-up across a reboot, not across a resume). So before doing anything we check
# the wall clock against the configured alarm time and bail out if we are late.
DIR=/home/eitan/.local/share/sunrise-alarm
CFG="$HOME/.config/sunrise-alarm/config.json"
LOG="$DIR/engine.log"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
[ -S "$XDG_RUNTIME_DIR/.ydotool_socket" ] && export YDOTOOL_SOCKET="$XDG_RUNTIME_DIR/.ydotool_socket"

stamp() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# --- single instance: never stack two alarms on top of each other ---
exec 9>"$XDG_RUNTIME_DIR/sunrise-alarm.lock"
if ! flock -n 9; then
  stamp "alarm already running; second trigger ignored"
  exit 0
fi

# --- enabled flag + staleness decision (one python call) ---
DECISION=$(python3 - "$CFG" <<'PY'
import json, sys, datetime
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    c = {}
if not c.get("enabled", True):
    print("SKIP disabled"); raise SystemExit
t = str(c.get("alarm_time", "07:40"))
grace = float(c.get("max_late_min", 15))     # how late a trigger may be and still fire
try:
    hh, mm = (int(x) for x in t.split(":")[:2])
except Exception:
    hh, mm = 7, 40
now = datetime.datetime.now()
base = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
# nearest occurrence of HH:MM (yesterday / today / tomorrow), so 23:5x -> 00:0x works
target = min((base + datetime.timedelta(days=d) for d in (-1, 0, 1)),
             key=lambda x: abs((now - x).total_seconds()))
late = (now - target).total_seconds() / 60.0
ok = -2.0 <= late <= grace                   # -2 min covers timer/clock jitter
print("%s late=%.1fmin grace=%.0fmin alarm=%s" % ("RUN" if ok else "SKIP", late, grace, t))
PY
)

case "$DECISION" in
  SKIP*)
    stamp "not firing: $DECISION"
    exit 0 ;;
  RUN*)
    stamp "firing: $DECISION" ;;
  *)
    # config unreadable or python broke: fail safe by NOT blasting the screen
    stamp "not firing: undecidable ($DECISION)"
    exit 0 ;;
esac

python3 "$DIR/engine.py" real

# one-shot alarms disarm themselves after firing
REPEAT=$(python3 -c "import json;print(json.load(open('$CFG')).get('repeat_daily',True))" 2>/dev/null)
if [ "$REPEAT" = "False" ]; then
  systemctl --user disable --now sunrise-alarm.timer 2>/dev/null
  gsettings set org.gnome.desktop.screensaver lock-enabled true 2>/dev/null
  pkexec "$DIR/install_wake.sh" remove 2>/dev/null || true
fi
