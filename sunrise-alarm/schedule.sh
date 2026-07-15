#!/bin/bash
# Arms/disarms the alarm. Installs a persistent user timer (fires the alarm),
# turns off auto-lock (so the light shows through a resume), and installs a
# root RTC-wake timer (so it survives suspend). Prints status lines.
#   schedule.sh arm <HH:MM>
#   schedule.sh disarm
DIR=/home/eitan/.local/share/sunrise-alarm
UDIR="$HOME/.config/systemd/user"
action="$1"; TIME="$2"

case "$action" in
  arm)
    HH="${TIME%%:*}"; MM="${TIME##*:}"
    mkdir -p "$UDIR"
    cat > "$UDIR/sunrise-alarm.service" <<EOF
[Unit]
Description=Sunrise Alarm
[Service]
Type=oneshot
ExecStart=$DIR/run_alarm.sh
EOF
    cat > "$UDIR/sunrise-alarm.timer" <<EOF
[Unit]
Description=Sunrise Alarm timer
[Timer]
OnCalendar=*-*-* ${HH}:${MM}:00
AccuracySec=1s
Persistent=false
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS 2>/dev/null
    systemctl --user enable --now sunrise-alarm.timer
    # don't lock overnight, so the sunrise is visible after a resume
    gsettings set org.gnome.desktop.screensaver lock-enabled false
    gsettings set org.gnome.desktop.screensaver ubuntu-lock-on-suspend false 2>/dev/null || true
    # GUARANTEE: keep the machine awake while armed (RTC-wake is unreliable on this hw),
    # so the timer definitely fires. The RTC wake below is an additional best-effort layer.
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
    # RTC wake ~2 min before the alarm (needs root)
    T=$(date -d "${HH}:${MM}" +%s); W=$((T-120))
    WH=$(date -d "@$W" +%H); WM=$(date -d "@$W" +%M)
    echo "arming user timer @ ${HH}:${MM}, RTC wake @ ${WH}:${WM}"
    pkexec "$DIR/install_wake.sh" install "$WH" "$WM" || echo "WARN: RTC wake not installed (auth cancelled); alarm still fires if awake"
    echo "--- armed ---"
    systemctl --user list-timers 2>/dev/null | grep sunrise-alarm || true
    ;;
  disarm)
    systemctl --user disable --now sunrise-alarm.timer 2>/dev/null
    gsettings set org.gnome.desktop.screensaver lock-enabled true
    gsettings set org.gnome.desktop.screensaver ubuntu-lock-on-suspend true 2>/dev/null || true
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'suspend'
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'suspend'
    pkexec "$DIR/install_wake.sh" remove || echo "WARN: could not remove RTC wake"
    echo "--- disarmed ---"
    ;;
  *)
    echo "usage: schedule.sh arm <HH:MM> | disarm" >&2; exit 2 ;;
esac
