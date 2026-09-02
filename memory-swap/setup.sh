#!/usr/bin/env bash
# Reproduce the low-memory fix for the 16 GB machine: zram + big swap + earlyoom.
# Run as root:  sudo bash setup.sh
# Idempotent: safe to re-run.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo bash $0"; exit 1; fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installing packages (systemd-zram-generator, earlyoom)"
apt-get update -y
apt-get install -y systemd-zram-generator earlyoom

echo "==> Installing config files into /etc"
install -D -m 0644 "$HERE/etc/systemd/zram-generator.conf" /etc/systemd/zram-generator.conf
install -D -m 0644 "$HERE/etc/default/earlyoom"            /etc/default/earlyoom
install -D -m 0644 "$HERE/etc/sysctl.d/99-zram-swap.conf"  /etc/sysctl.d/99-zram-swap.conf

echo "==> Applying sysctl"
sysctl --system >/dev/null

echo "==> Ensuring an 8 GB /swap2.img overflow swapfile"
if ! swapon --show=NAME --noheadings | grep -qx /swap2.img; then
  if [ ! -f /swap2.img ]; then
    fallocate -l 8G /swap2.img || { rm -f /swap2.img; dd if=/dev/zero of=/swap2.img bs=1M count=8192 status=none; }
  fi
  chmod 600 /swap2.img
  mkswap /swap2.img >/dev/null
  swapon --priority 10 /swap2.img
fi
grep -qE '^[[:space:]]*/swap2.img[[:space:]]' /etc/fstab || echo '/swap2.img none swap sw,pri=10 0 0' >> /etc/fstab

echo "==> Memory protection for the desktop cgroup chain"
# GNOME Shell already asks for MemoryMin=768M / MemoryLow=1.5G, but cgroup v2
# hands protection DOWN: a cgroup's effective protection is capped by its
# ancestors', and every ancestor here had memory.min = memory.low = 0. So the
# shell's protection was silently zero and the kernel swapped the compositor
# out mid-frame, which looks exactly like screen jitter. Give the ancestors a
# reservation so the shell's own values can bite. Children that ask for no
# protection (Chrome, etc.) claim none of it.
for u in user.slice user-.slice user@.service; do
  install -D -m 0644 "$HERE/etc/systemd/system/$u.d/50-memory-protection.conf" \
          "/etc/systemd/system/$u.d/50-memory-protection.conf"
done
systemctl daemon-reload
# Apply to the already-running units too, so no reboot is needed.
systemctl set-property --runtime user.slice        MemoryMin=1G MemoryLow=2G || true
systemctl set-property --runtime "user-$(id -u "${SUDO_USER:-eitan}").slice"    MemoryMin=1G MemoryLow=2G || true
systemctl set-property --runtime "user@$(id -u "${SUDO_USER:-eitan}").service"  MemoryMin=1G MemoryLow=2G || true
# The last link in the chain, session.slice, is a USER unit: see install-user.sh

echo "==> Enabling services"
systemctl daemon-reload
systemctl enable --now earlyoom
# zram is created by systemd-zram-generator at boot (systemd-zram-setup@zram0.service).
# Start it now too so the running system gets zram without a reboot:
systemctl start systemd-zram-setup@zram0.service 2>/dev/null || true

echo "==> Done. Current state:"
swapon --show
free -h
echo
echo "Note: assumes the distro default /swap.img (4 GB) already exists."
echo "zram activates fully on the next boot regardless."
