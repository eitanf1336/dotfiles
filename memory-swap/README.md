# memory-swap: stop the OOM crashes, freezes, stutter and slowness on this laptop

The laptop has 16 GB RAM. It was OOM-killing Chrome constantly, sometimes
thrashing into a hard freeze that needed a power-cycle, and even with RAM to
spare it felt sluggish next to Windows. Four separate causes, all fixed here
(2026-07-12, 2026-07-15 and 2026-08-19).

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

## Cause 3: the desktop had no CPU priority at all (2026-08-19)

Causes 1 and 2 are about *memory*. This one is about why the machine still felt
like glue with plenty of RAM free, which is the complaint that actually persisted.

`session.slice` (where GNOME Shell, Xwayland and every terminal-spawned process
live) had `cgroup.subtree_control = memory pids`. **No `cpu`.** With the cpu
controller not enabled there, GNOME Shell's cgroup had no `cpu.weight` file at
all, so the compositor competed against every build, dev server and inference job
as an ordinary bag of threads. One ONNX request taking 13 of 20 hardware threads
was enough to make the whole desktop stutter, with memory pressure at ~0%.

Windows does foreground/UI priority boosting by default. Ubuntu does not. That is
the entire difference in feel.

`user-dropins/` fixes it. Setting `CPUWeight=` on a unit inside `session.slice`
makes systemd enable the cpu controller there, which is what creates the knob:

| unit | `CPUWeight` | why |
|---|---|---|
| `org.gnome.Shell@ubuntu.service` | **10000** | the compositor must never wait behind background compute |
| `pipewire` / `wireplumber` / `pipewire-pulse` | **5000** | a missed audio buffer is an audible click |
| `vte-spawn-*.scope` (every terminal tree) | **20** | builds, dev servers and agent jobs yield |
| background services (`testbed-*`, `distillsignal-api`) | **30** + `CPUQuota=800%` | a parked dev server can never take the box |

`CPUWeight` is a **share, not a cap**: with the machine idle a build still gets
every core. It only decides who yields when the CPU is full, and there the
compositor has to win. The shell also gets `MemoryMin=768M`, which is *hard*
reclaim protection. `MemoryLow` alone is only advisory and the shell was sitting
on 139 MB of swap in spite of it, which is most of the "molasses after heavy
load" feeling.

`vte-spawn-.scope.d/` is a prefix drop-in, the same mechanism
`/usr/lib/systemd/user/vte-spawn-.scope.d/defaults.conf` already uses, so it
applies to every terminal-spawned scope automatically. This is the half that
per-service drop-ins cannot reach: dev servers and agent jobs live in these
transient scopes, not in `app.slice`.

### Measured, on a 20-thread i7-12700H under 5 concurrent Claude agents

| | before | after |
|---|---|---|
| load average | 41 | 17 |
| CPU pressure (`some avg10`) | 52.7% | 1.0% |
| GNOME Shell stall (`cpu.pressure some avg10`) | 4.95% | **0.00%** |
| memory pressure (`some avg10`) | 15.9% | 0.00% |

Verify at any time:

```bash
S=/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice
cat $S/org.gnome.Shell@ubuntu.service/cpu.weight   # want 10000
cat $S/org.gnome.Shell@ubuntu.service/cpu.pressure # want some avg10 near 0
```

If `cpu.weight` does not exist, the cpu controller is not delegated and every
`CPUWeight=` here is being silently ignored.

### Two runaway patterns this also caught

- **A crash-looping unit is a permanent CPU tax.** `distillsignal-api.service`
  had restarted **62 times in 9 minutes** because an agent-launched server
  already held its port, and uvicorn exits 3 on "address already in use". Each
  attempt burned ~3.7 s of CPU importing python + onnxruntime: about 40% of a
  core, forever, surviving every reboot. Fixed with `ExecCondition=` (a non-zero
  exit makes systemd *skip* the start cleanly instead of marking it failed and
  re-triggering `Restart=`) plus `RestartSec=30`.
- **A stuck shutdown can outlive its owner.** A uvicorn whose agent had finished
  had closed its listening socket but was still grinding a request through an
  unbounded ONNX scoring loop: 12 of 20 threads and 1.9 GB, invisible to every
  "is anything listening?" check. `CPUQuota=` on the service bounds this class of
  bug permanently.

## Cause 4: the CPU was pinned at a quarter speed (2026-08-19)

The one that survived all three fixes above, and the one that actually felt worst.

GNOME's `power-saver-profile-on-low-battery` (gsettings, default **true**) flips
power-profiles-daemon to `power-saver` when the battery runs low. **It never
flips it back.** Plug the laptop in and the profile stays there: `EPP=power`,
all 20 cores pinned at **1200 MHz on a chip rated 4600 MHz**, at 69 C with
`core_throttle_count=0`. Not thermal, not load, not memory.

This is invisible to every normal check. `top`, `free`, `/proc/pressure/*` and
`uptime` all look healthy, because the machine genuinely is not busy. It is just
running at a quarter speed. Measured with the same single-core loop:

| profile | time | clock under load |
|---|---|---|
| `power-saver` | 1.35 s | 1100 MHz (no boost at all) |
| `balanced` | **0.54 s** | 2804 MHz |

**Always check this first when "it is slow" and nothing is loaded:**

```bash
powerprofilesctl get
grep '^cpu MHz' /proc/cpuinfo | head -3
cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference
```

`bin/power-profile-auto` + `systemd/power-profile-auto.service` supply the half
GNOME is missing: on a battery -> AC transition (and once at startup), if the
profile is `power-saver`, set it back to `balanced`. It is **edge-triggered, not
level-triggered**, and only touches `power-saver`, so choosing a profile yourself
(including power-saver while plugged in) sticks until you physically replug.
Unplugging is left entirely alone, since GNOME's low-battery rule owns that.

## Reproduce (fresh machine)

```bash
sudo bash setup.sh     # system half: packages, zram, swap2, earlyoom, sysctl
bash install-user.sh   # user half: spare reaper + desktop-priority drop-ins (no root)
```

Both idempotent. zram fully activates on the next boot regardless.

## Note

This makes 16 GB usable under a heavy load; it does not make it 32 GB. The real
cure for genuine over-subscription is more RAM.
