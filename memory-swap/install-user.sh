#!/usr/bin/env bash
# Install the USER-level half of the responsiveness fix. No root needed. Idempotent.
# For the system-level half (zram/swap/earlyoom) run: sudo bash setup.sh
#
# Two independent things live here:
#   1. claude-spare-reaper  -- reclaims RAM leaked by Claude Code (Cause 2)
#   2. systemd user drop-ins -- give the desktop CPU priority over background
#                               work, so a busy machine still feels smooth (Cause 3)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
SYSD="$HOME/.config/systemd/user"
mkdir -p "$BIN" "$SYSD"

echo "==> claude-spare-reaper -> $BIN"
install -m 0755 "$HERE/claude-spare-reaper" "$BIN/claude-spare-reaper"

echo "==> systemd user units -> $SYSD"
install -m 0644 "$HERE/claude-spare-reaper.service" "$SYSD/claude-spare-reaper.service"
install -m 0644 "$HERE/claude-spare-reaper.timer"   "$SYSD/claude-spare-reaper.timer"

echo "==> desktop-priority drop-ins -> $SYSD"
# GNOME Shell, the audio stack, and every terminal-spawned scope. The shell and
# pipewire get a large CPU share; terminal scopes get a small one. See README
# "Cause 3" for why this is what actually fixes desktop stutter under load.
for d in org.gnome.Shell@ubuntu.service.d vte-spawn-.scope.d \
         pipewire.service.d wireplumber.service.d pipewire-pulse.service.d \
         app.slice.d; do
  [ -d "$HERE/user-dropins/$d" ] || continue
  install -d -m 0755 "$SYSD/$d"
  install -m 0644 "$HERE/user-dropins/$d"/*.conf "$SYSD/$d/"
done

# Long-running background user services: cap them so a parked dev server can
# never take the whole machine. Only units that actually exist are touched.
echo "==> resource caps on background services"
LIMITS="$HERE/user-dropins/background-services/50-resource-limits.conf"
for u in testbed-distillsignal testbed-apeirion testbed-surfstatus distillsignal-api; do
  [ -f "$SYSD/$u.service" ] || continue
  install -d -m 0755 "$SYSD/$u.service.d"
  install -m 0644 "$LIMITS" "$SYSD/$u.service.d/50-resource-limits.conf"
  echo "    capped $u"
done

systemctl --user daemon-reload
systemctl --user enable --now claude-spare-reaper.timer

echo
echo "==> verifying the CPU controller is actually delegated"
SLICE=/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/session.slice
if [ -r "$SLICE/org.gnome.Shell@ubuntu.service/cpu.weight" ]; then
  echo "    gnome-shell cpu.weight = $(cat "$SLICE/org.gnome.Shell@ubuntu.service/cpu.weight") (want 10000)"
else
  echo "    WARNING: no cpu.weight on the shell cgroup. The cpu controller is not"
  echo "    delegated to user@.service, so CPUWeight= is being silently ignored."
fi

echo
echo "==> done. Timer:"
systemctl --user list-timers claude-spare-reaper.timer --no-pager
echo
echo "Check what the reaper reclaims with: journalctl --user -u claude-spare-reaper"
