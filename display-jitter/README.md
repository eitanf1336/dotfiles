# Screen jitter: the actual cause, and the permanent fix

For a year the laptop's screens would randomly start showing jittery graphical
corruption. `Super+F5` (`bin/fix-screen`) cleared it by bouncing the VT, which
forces a full modeset, but it always came back.

## Why it happened

The machine has two GPUs and, when docked, no enabled display on the one GNOME
chose to render with:

| device | driver | outputs |
|---|---|---|
| `card0` | `nvidia` | `HDMI-A-1` — the **main monitor** |
| `card1` | `i915` | `eDP-1` — the built-in panel, **switched off** |
| `card2`..`card5` | `evdi` | the DisplayLink dock screens |

Mutter picks its primary GPU by looking for a built-in panel, and logs so:

```
GPU /dev/dri/card1 selected primary from builtin panel presence
Failed to initialize accelerated iGPU/dGPU framebuffer sharing: Not hardware accelerated
```

So the entire desktop was rendered on the Intel GPU — which drives **nothing**,
because the lid panel is off — and then every single frame was copied across to
the NVIDIA card for the main monitor. That cross-GPU path has no hardware
acceleration on this pair, so mutter falls back to a fragile CPU copy that
periodically fails:

```
Failed to lock front buffer on /dev/dri/card1: gbm_surface_lock_front_buffer failed
```

Every one of those is a dropped/garbled frame. **100% of them were on `card1`**,
the GPU with no displays attached. That is the jitter.

## SOLVED (2026-09-03): detune the DisplayLink screens to 50Hz

Everything below this section is the record of chasing the wrong GPU. The
actual cause was found by testing rather than reasoning: stop the DisplayLink
daemon and count.

```
DisplayLink running   7 front-buffer failures / 5 min
DisplayLink stopped   0 failures / 2 min
```

It was never the NVIDIA hand-off. With the dock screens out of the picture the
main screen was clean. Then, with them back but detuned:

```
dock screens @ 60Hz   1.40 failures/min
dock screens @ 50Hz   0.00 over ten minutes   (60Hz rate predicted ~14)
```

**And DisplayLinkManager's CPU did not change** (~72% of a core either way). So
this is not a load problem, it is a frame-timing one: with every screen at
60Hz, all three copies off the Intel primary are demanded in lockstep on every
frame and the renderer periodically has no free buffer. Running the dock
screens at 50Hz breaks the lockstep, and a 17% refresh change removes 100% of
the failures at identical CPU cost.

Applied by `bin/set-screen-modes` + `systemd/set-screen-modes.service` at every
login, because asking mutter to persist it did nothing (`monitors.xml` was not
even written). `set-screen-modes --show` prints what is running and whether it
matches. The pinned set is the exact combination that measured zero, main
screen at 120Hz included.

The cost is that two 1080p side monitors run at 50Hz instead of 60, which is
invisible on a desktop. `jitter-watch` stays enabled as a safety net and now
has nothing to do.

## The lesson

Three GPU-level fixes were attempted before anyone measured which component was
actually responsible, and two of them broke a working setup: NVIDIA-primary
killed the dock screens, and disabling DRM format modifiers left the main
monitor black at boot. A single two-minute experiment (stop the daemon, count
the failures) identified the real cause and pointed straight at a fix that
costs nothing and risks nothing. Measure which part is guilty before changing
any part.

## What did NOT work: making NVIDIA the primary GPU

The obvious fix is to tag the NVIDIA card `mutter-device-preferred-primary`, so
the main monitor is a direct scanout with no cross-GPU copy. Tried it on
2026-09-03. It **worked** on the target: front-buffer failures went from ~5/hour
to zero and the HDMI monitor was clean.

It also made the two DisplayLink dock screens unusable — the pointer barely
moved on them. Flipping the primary GPU does not remove the copy, it moves it:
the dock screens go from Intel -> evdi (fine) to NVIDIA -> evdi, and the
proprietary driver's readback for a secondary device is far slower than the
Intel one. Two working screens are worth more than one perfect one, so this is
reverted. `gpu-primary nvidia` still exists if it is ever worth revisiting.

## What ALSO did not work: disabling DRM format modifiers

Second attempt, same day: keep Intel primary and tag the NVIDIA card
`mutter-device-disable-kms-modifiers` (the tag mutter itself ships for GPUs
whose modifiers it cannot rely on), reasoning that the dock screens never touch
that device so the worst case would be no change.

The worst case was not no change. **The HDMI monitor came up black at boot** and
had to be physically unplugged. Reverted, along with everything else here.

## Where this stands

Nothing is installed. The machine is on stock behaviour: Intel primary, the
occasional `gbm_surface_lock_front_buffer failed` on the main screen, cleared
with **Super+F5** (`bin/fix-screen`) when it shows up.

Two ideas were tried and both cost a working setup, so the bar for a third is
high. The remaining untried options, in the order that risks least:

1. **Move the main monitor onto the dock** instead of the laptop HDMI port. Then
   every display is Intel -> evdi and there is no cross-GPU copy at all. Costs a
   cable swap, not a boot.
2. An **Xorg session**, where hybrid + DisplayLink + multi-monitor is far better
   behaved than Wayland.
3. Leave it. Super+F5 is a keystroke, and the failure rate is roughly 5/hour
   when idle, though it climbs to several a minute under load.

**An Xorg session is not the easy escape it looks like.** Checked 2026-09-03:
`/usr/share/xsessions/` is EMPTY on this box, only the Wayland session is
installed, the NVIDIA X driver is absent (`modesetting_drv.so` is the only one
present) and there is no DisplayLink xorg.conf.d snippet. So "just pick Xorg at
the login screen" is not available; it would mean installing an X session plus
configuring DisplayLink for X, which is a bigger change than the two that
already broke a screen.

## The workaround to actually use: `fix-screen-soft`

`fix-screen` (Super+F5) bounces the graphical VT. That clears the corruption,
but a VT switch tears down and rebuilds the whole session's device access,
which stops Spotify and interrupts anything else holding a device. That cost is
what made the automatic version unusable.

`bin/fix-screen-soft` does the same job without touching the VT: it flips the
affected screen to another refresh rate at the SAME resolution and straight
back. That is a full modeset with fresh framebuffers, which is the part that
clears the corruption, while nothing else moves:

* no VT switch, so audio and every other device holder is untouched
* the resolution never changes, so the desktop geometry never changes, so no
  windows are relocated

The first design switched the output off and on instead. Two problems, both
found before shipping it: mutter rejects the gap in the layout with "Logical
monitors not adjacent", and more importantly, removing a monitor makes GNOME
relocate its windows and they do not come back. The refresh-rate flip has
neither problem. It needs a second mode at the current resolution, which this
monitor has (2560x1440 at 60, 120 and 144); if a screen has none, the tool
falls back to off/on and says so first.

Configs are applied with method=TEMPORARY, so `monitors.xml` is never written,
and the restore is in a `finally` block. Verified live: layout came back
byte-identical, and no VT switch appears in the journal.

## `jitter-watch`, running

`bin/jitter-watch` + `systemd/jitter-watch.service` follow the journal and run
`fix-screen` automatically when a BURST of front-buffer failures appears (4
inside 20s, at most one bounce per 2 minutes). Deliberately conservative: a VT
bounce flashes every screen, so firing on a single stray failure would be worse
than the jitter.

It calls **`fix-screen-soft`**, never `fix-screen`. That distinction is the
whole reason it is safe to run automatically: the VT bounce would stop Spotify
every time it fired.

It fires on **every** failure, with only a cooldown to stop it thrashing.

Three earlier tunings (4-in-20s, 3-in-60s, 2-in-90s) all assumed a lone dropped
frame is invisible and only clusters matter. That assumption was wrong, and
this is the observation that killed it:

```
failures at 11:47:32, 11:49:21, 11:51:02   ~100s apart, no cluster at all
user at that moment:                        "again it jitters"
```

The corruption is not a transient flicker that needs repeating to be seen. It
is **persistent**: one failure dirties the screen and it stays dirty until a
modeset clears it. That is precisely why this ever needed a keypress. So a
single failure is already a visible defect, and every "wait for a second one"
threshold just meant staring at the first.

A correction worth recording: the soft reset was briefly written off as useless
because failures still appeared in the log after it ran. They did, and that is
expected. The reset clears the corruption already on screen; it does not stop
new failures happening. Judging the remedy by whether failures stopped was the
wrong test entirely.

Turn it off with `systemctl --user disable --now jitter-watch`.

The guard machinery that used to live here (`gpu-primary-guard`, the boot
counter, the auto-revert) is gone too, since there is no rule left to guard.
`bin/gpu-primary` still exists as a toggle, but read the two sections above
before using it.

```
gpu-primary status     # what the running session picked, and the front-buffer
                       # failure count this boot. Safe, read-only.
gpu-primary nvidia     # DON'T: kills the DisplayLink screens (see above)
gpu-primary intel      # stock behaviour, i.e. what is in place now
```

Mutter chooses its primary GPU once at startup, so a change **takes effect at
the next login**.

## The safety net

Picking the wrong primary GPU could in principle stop the machine reaching a
desktop, and this box has a history of GDM login loops (see
`../nvidia/README.md`). So `gpu-primary-guard.service` runs before GDM on every
boot and counts boots that never reach a working session; `gpu-primary-ok`
(a user unit) resets that counter once GNOME Shell answers on D-Bus. After two
boots with no successful login, the third removes the udev rule automatically
and the machine comes back on the stock Intel path.

Manual recovery, if it ever comes to that: Ctrl+Alt+F3, log in, `gpu-primary intel`.

## Install

```
sudo bash setup.sh
systemctl --user enable gpu-primary-ok.service
```

## The second, smaller cause

Memory pressure produces the same visual symptom, and `Super+F5` does *not*
fix that one (it returns within a minute or two). GNOME Shell ships
`MemoryMin=768M` / `MemoryLow=1.5G`, but in cgroup v2 protection is handed down
from the parent, and every ancestor slice had `memory.min = memory.low = 0`, so
the shell's effective protection was **zero** and the kernel was swapping the
compositor out mid-frame. Fixed by setting protection on the ancestors; see
`../memory-swap/`.

Tell the two apart:

```
journalctl -b | grep -c 'lock front buffer'      # GPU cause: high and bursty
grep VmSwap /proc/$(pgrep -x gnome-shell)/status # memory cause: non-zero here
```
