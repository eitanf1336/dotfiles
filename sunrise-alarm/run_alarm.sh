#!/bin/bash
# Env wrapper the systemd --user timer calls. Fixes up the graphical-session env
# (systemd user units don't always inherit WAYLAND_DISPLAY etc.) then runs the engine.
DIR=/home/eitan/.local/share/sunrise-alarm
CFG="$HOME/.config/sunrise-alarm/config.json"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
[ -S "$XDG_RUNTIME_DIR/.ydotool_socket" ] && export YDOTOOL_SOCKET="$XDG_RUNTIME_DIR/.ydotool_socket"

# respect the enabled flag
EN=$(python3 -c "import json;print(json.load(open('$CFG')).get('enabled',True))" 2>/dev/null)
if [ "$EN" = "False" ]; then echo "alarm disabled; skipping" >> "$DIR/engine.log"; exit 0; fi

python3 "$DIR/engine.py" real

# one-shot alarms disarm themselves after firing
REPEAT=$(python3 -c "import json;print(json.load(open('$CFG')).get('repeat_daily',True))" 2>/dev/null)
if [ "$REPEAT" = "False" ]; then
  systemctl --user disable --now sunrise-alarm.timer 2>/dev/null
  gsettings set org.gnome.desktop.screensaver lock-enabled true 2>/dev/null
  pkexec "$DIR/install_wake.sh" remove 2>/dev/null || true
fi
