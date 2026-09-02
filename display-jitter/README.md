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

## The fix actually in place

Keep Intel primary, and tell mutter not to use DRM format modifiers on the
NVIDIA device (`etc/udev/rules.d/62-mutter-nvidia-no-modifiers.rules`). mutter
ships this same tag in `/lib/udev/rules.d/61-mutter.rules` for GPUs whose
modifiers it cannot rely on. The theory: the shared-framebuffer setup already
says "Not hardware accelerated", and without modifiers both drivers fall back to
a plain linear layout that the primary can actually lock.

The dock screens are untouched by this, because their path (Intel -> evdi) does
not involve the NVIDIA device at all. So the worst case is no change, not a
regression.

Switch it at any time:

```
gpu-primary status     # what is configured, what the running session picked,
                       # and the front-buffer failure count this boot
gpu-primary nvidia     # render on the dGPU (the fix)
gpu-primary intel      # stock behaviour
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
