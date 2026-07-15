#!/bin/bash
# Runs as ROOT (via pkexec). Installs/removes a system RTC-wake timer so the
# machine resumes from suspend a couple minutes before the alarm. The paired
# service just holds a sleep inhibitor for 10 min so it doesn't re-suspend
# before the user's alarm fires.
#   install_wake.sh install <HH> <MM>
#   install_wake.sh remove
set -e
ACTION="$1"
SVC=/etc/systemd/system/sunrise-wake.service
TMR=/etc/systemd/system/sunrise-wake.timer

case "$ACTION" in
  install)
    HH="$2"; MM="$3"
    cat > "$SVC" <<EOF
[Unit]
Description=Sunrise Alarm RTC wake (hold system awake briefly)
[Service]
Type=oneshot
ExecStart=/usr/bin/systemd-inhibit --what=sleep --why=sunrise-alarm /bin/sleep 600
EOF
    cat > "$TMR" <<EOF
[Unit]
Description=Sunrise Alarm RTC wake timer
[Timer]
OnCalendar=*-*-* ${HH}:${MM}:00
WakeSystem=true
AccuracySec=1s
Persistent=false
[Install]
WantedBy=timers.target
EOF
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
