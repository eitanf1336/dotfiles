#!/usr/bin/env bash
# Install the permanent screen-jitter fix: make mutter render on the NVIDIA
# dGPU instead of the display-less Intel iGPU, plus the guard that reverts it
# automatically if boots ever stop reaching a desktop. See README.md.
# Run as root:  sudo bash setup.sh
# Idempotent: safe to re-run.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo bash $0"; exit 1; fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-eitan}"

echo "==> udev rule: no DRM format modifiers on the NVIDIA dGPU"
# NOT the preferred-primary rule: making NVIDIA primary fixed the HDMI monitor
# and made the two DisplayLink dock screens unusable. See README.md.
install -D -m 0644 "$HERE/etc/udev/rules.d/62-mutter-nvidia-no-modifiers.rules" \
        /etc/udev/rules.d/62-mutter-nvidia-no-modifiers.rules
udevadm control --reload-rules
udevadm trigger -s drm

echo "==> guard scripts and units"
install -D -m 0755 "$HERE/usr/local/lib/gpu-primary-guard" /usr/local/lib/gpu-primary-guard
install -D -m 0755 "$HERE/usr/local/lib/gpu-primary-ok"    /usr/local/lib/gpu-primary-ok
install -D -m 0644 "$HERE/etc/systemd/system/gpu-primary-guard.service" \
        /etc/systemd/system/gpu-primary-guard.service
install -D -m 0644 "$HERE/usr/lib/systemd/user/gpu-primary-ok.service" \
        /usr/lib/systemd/user/gpu-primary-ok.service

install -d -m 0755 /var/lib/gpu-primary
echo 0 > /var/lib/gpu-primary/failcount
chown "$TARGET_USER:$TARGET_USER" /var/lib/gpu-primary/failcount
chmod 0644 /var/lib/gpu-primary/failcount

systemctl daemon-reload
systemctl enable gpu-primary-guard.service

cat <<EOF

Done. Still to do, as $TARGET_USER (not root):
    systemctl --user enable gpu-primary-ok.service

Then log out and back in. Verify with:
    gpu-primary status
The "running session" line should read card0, and the front-buffer failure
count should stay at 0.
EOF
