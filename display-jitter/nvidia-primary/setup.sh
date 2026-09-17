#!/usr/bin/env bash
# Render the desktop on the NVIDIA dGPU (away setup: main screen on laptop HDMI,
# side screens on an Intel USB-C hub, no DisplayLink), plus the guard that
# reverts it after two boots or two logins that never reach a working shell.
# Run as root. Idempotent. Undo: gpu-primary intel, then log out.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root"; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in gpu-primary-guard gpu-primary-login gpu-primary-ok; do
  install -D -m 0755 "$HERE/usr/local/lib/$f" "/usr/local/lib/$f"
done
for f in gpu-primary-guard.service gpu-primary-guard.path gpu-primary-guard-check.service; do
  install -D -m 0644 "$HERE/etc/systemd/system/$f" "/etc/systemd/system/$f"
done
for f in gpu-primary-ok.service gpu-primary-login.service; do
  install -D -m 0644 "$HERE/usr/lib/systemd/user/$f" "/usr/lib/systemd/user/$f"
done
install -d -m 0755 /var/lib/gpu-primary
for c in bootcount logincount; do
  echo 0 > "/var/lib/gpu-primary/$c"; chown eitan:eitan "/var/lib/gpu-primary/$c"; chmod 0644 "/var/lib/gpu-primary/$c"
done
systemctl daemon-reload
systemctl enable gpu-primary-guard.service gpu-primary-guard.path
systemctl start gpu-primary-guard.path
systemctl --global enable gpu-primary-ok.service gpu-primary-login.service
