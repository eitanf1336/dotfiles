#!/usr/bin/env bash
# Install the USER-level half of the memory fix: the Claude Code spare reaper.
# No root needed. Idempotent. For the system-level half (zram/swap/earlyoom)
# run: sudo bash setup.sh
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

systemctl --user daemon-reload
systemctl --user enable --now claude-spare-reaper.timer

echo "==> done. Timer:"
systemctl --user list-timers claude-spare-reaper.timer --no-pager
echo
echo "Check what it reaps with: journalctl --user -u claude-spare-reaper"
