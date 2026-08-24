#!/bin/bash
# Runs as ROOT (via pkexec). Installs/removes a system RTC-wake timer so the
# machine resumes from suspend a couple minutes before the alarm. The paired
# service holds a sleep + lid-switch inhibitor (see wake_hold.sh) so the machine
# cannot drop straight back to sleep before the alarm actually fires.
#   install_wake.sh install <HH> <MM>
#   install_wake.sh remove
set -e
ACTION="$1"
DIR=/home/eitan/.local/share/sunrise-alarm
SVC=/etc/systemd/system/sunrise-wake.service
TMR=/etc/systemd/system/sunrise-wake.timer

case "$ACTION" in
  install)
    HH="$2"; MM="$3"
    cat > "$SVC" <<EOF2
[Unit]
Description=Sunrise Alarm RTC wake (hold system awake until the alarm fires)
# Order after the resume path so we are not fighting an in-flight suspend op.
After=suspend.target sleep.target
[Service]
Type=oneshot
ExecStart=$DIR/wake_hold.sh 2700
EOF2
    cat > "$TMR" <<EOF2
[Unit]
Description=Sunrise Alarm RTC wake timer
[Timer]
OnCalendar=*-*-* ${HH}:${MM}:00
WakeSystem=true
AccuracySec=1s
Persistent=false
[Install]
WantedBy=timers.target
EOF2
    systemctl daemon-reload
    systemctl enable --now sunrise-wake.timer
    echo "installed sunrise-wake.timer @ ${HH}:${MM}"
    ;;
  remove)
    systemctl disable --now sunrise-wake.timer 2>/dev/null || true
    rm -f "$SVC" "$TMR"
    systemctl daemon-reload
    echo "removed sunrise-wake"
    ;;
  *)
    echo "usage: install_wake.sh install <HH> <MM> | remove" >&2; exit 2 ;;
esac
