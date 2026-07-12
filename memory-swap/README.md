# memory-swap: stop OOM crashes and freezes on the 16 GB machine

The laptop has 16 GB RAM and a heavy normal load (Chrome with many tabs,
JetBrains IDE, ffmpeg encodes, Spotify, VSCodium, several `claude`). Stock
Ubuntu shipped only a 4 GB swapfile, so under load the kernel OOM-killed Chrome
tabs and, worse, the machine sometimes thrashed into a hard freeze that needed a
power-cycle. This folder is the fix, set up 2026-07-12.

## What it does

1. **zram** (`etc/systemd/zram-generator.conf`) via the `systemd-zram-generator`
   package: a 12 GB zstd-compressed swap device that lives in RAM, priority 100
   so it is used first. On this workload it compresses roughly 4:1, so it is far
   faster than disk swap and effectively adds several GB of usable memory.
2. **A bigger disk safety net**: keeps Ubuntu's default `/swap.img` (4 GB) and
   adds `/swap2.img` (8 GB, priority 10). See `fstab-swap-lines.txt`. Total swap
   is about 24 GB (12 zram + 12 disk).
3. **earlyoom** (`etc/default/earlyoom`): a freeze-guard. When available RAM and
   free swap both drop below 5%, it cleanly kills the biggest memory hog
   (Chrome/ffmpeg/IDE) BEFORE the machine can lock up, and is configured to never
   kill the desktop (gnome-shell, Xwayland, systemd, pipewire) or `claude`.
4. **sysctl tuning** (`etc/sysctl.d/99-zram-swap.conf`): high swappiness so the
   fast zram is preferred, and a larger free-memory watermark so `kswapd`
   reclaims early instead of hitting the OOM wall during bursts.

## Reproduce (fresh machine)

```bash
sudo bash setup.sh
```

Idempotent. Installs the two packages, drops the configs into `/etc`, creates
`/swap2.img`, applies sysctl, and enables the services. zram fully activates on
the next boot regardless.

## Note

This makes 16 GB usable under the load; it does not make it 32 GB. earlyoom may
still occasionally drop a single background Chrome tab under peak load, which is
by design (a graceful tab reload instead of a full-system freeze). The real cure
is more RAM.
