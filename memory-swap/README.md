# memory-swap: stop the OOM crashes and freezes on the 16 GB machine

The laptop has 16 GB RAM. It was OOM-killing Chrome constantly and sometimes
thrashing into a hard freeze that needed a power-cycle. Two separate causes, both
fixed here (2026-07-12 and 2026-07-15).

## Cause 1: swap was far too small

Stock Ubuntu shipped only a 4 GB swapfile, so under load there was nowhere to go
and the kernel started killing processes.

1. **zram** (`etc/systemd/zram-generator.conf`) via the `systemd-zram-generator`
   package: a 12 GB zstd-compressed swap device in RAM, priority 100 so it is
   used first. Compresses roughly 4:1 on this workload.
2. **Bigger disk safety net**: keeps Ubuntu's default `/swap.img` (4 GB) and adds
   `/swap2.img` (8 GB, priority 10). See `fstab-swap-lines.txt`. Total swap is
   about 24 GB (12 zram + 12 disk).
3. **earlyoom** (`etc/default/earlyoom`): freeze-guard. When available RAM and
   free swap both drop below 5% it kills the biggest memory hog BEFORE the
   machine can lock up. It avoids only true desktop essentials (gnome-shell,
   Xwayland, systemd, pipewire), so a crunch can never kill the session itself.
4. **sysctl** (`etc/sysctl.d/99-zram-swap.conf`): prefer the fast zram, and a
   larger free-memory watermark so `kswapd` reclaims early instead of hitting the
   OOM wall during bursts.

## Cause 2: Claude Code leaks background processes

This was the real culprit behind most of the pain. Claude Code's transient
daemons pre-warm spare pairs (`claude bg-pty-host` + `claude bg-spare`). When a
daemon exits, **its spares are not reaped**: they get reparented to
`systemd --user` and squat for 24h+, each holding roughly 230 MB RSS + 250 MB
swap. On 2026-07-15 there were 20 of them holding ~2.7 GB RSS + ~1.9 GB swap, and
a Claude-spawned `ugrep` had ballooned to 3.5 GB.

`claude-spare-reaper` + its systemd user timer fix this: every 10 minutes it
kills spare pairs that are provably dead and idle. It only reaps a pair when ALL
of these hold, so it can never kill a live session:

1. the exe really is under `~/.local/share/claude/versions/`
2. the `bg-pty-host` is reparented to init/systemd (its daemon is gone)
3. nothing is running inside it (its `bg-spare` child has no children)
4. it is older than 10 minutes

### A warning about earlyoom `--prefer`

An earlier version of `etc/default/earlyoom` used `--prefer ^(chrome|...)$` and
`--avoid ^(...|claude)$`. That made **Chrome the scapegoat for the Claude leak**:
Chrome was killed **130 times in one day** while the actual leaker was protected.
Do not reintroduce `--prefer`. Without it, earlyoom kills whatever is genuinely
the biggest hog, which is correct.

## Reproduce (fresh machine)

```bash
sudo bash setup.sh     # system half: packages, zram, swap2, earlyoom, sysctl
bash install-user.sh   # user half: the Claude spare reaper + timer (no root)
```

Both idempotent. zram fully activates on the next boot regardless.

## Note

This makes 16 GB usable under a heavy load; it does not make it 32 GB. The real
cure for genuine over-subscription is more RAM.
