# NVIDIA dGPU power fix

ASUS TUF Gaming F15 FX507ZV4, RTX 4060 Laptop, driver 595.71.05, kernel 7.0.0-22.

## The problem

On 2026-07-20 the machine was left idle for a few hours. The dGPU runtime-suspended
into D3cold, and the wake-up failed:

```
13:41:47  GSP task watchdog timeout @ pc:0x100cd12, partition:2#0, task:3
13:41:53  NVRM: Xid 119, Timeout after 9s of waiting for RPC response from GPU0 GSP!
                Expected function 4097 (GSP_INIT_DONE)
13:42:05  NVRM: Xid 154, GPU recovery action changed from 0x0 (None) to 0x1 (GPU Reset Required)
13:50:27  gnome-shell segfault in libnvidia-eglcore.so.595.71.05
```

The kernel stack was `nv_pmops_runtime_resume` -> `pci_pm_runtime_resume`, so the
failure is specifically **resume from D3cold**, not general GPU use. Once the GSP
firmware processor stopped answering, the GPU needed a full reset (reboot). The
session died with gnome-shell, the display fell back to the kernel console, and
nvidia-modeset printed `Error while waiting for GPU progress` every 5 seconds
(977 times) until the machine was power-cycled.

Driver 595.71.05 is already the newest in the Ubuntu repos, so there was no
update to fix it with.

## The fix

`etc/modprobe.d/zz-nvidia-power-fix.conf`:

```
options nvidia NVreg_DynamicPowerManagement=0x00
```

`0x00` disables dynamic power management, so the GPU never enters D3cold and the
broken resume path is never taken. Costs a few watts at idle (matters on battery,
not while docked).

`etc/modprobe.d/nvidia-runtimepm.conf` carries the same line and exists only to
shadow Ubuntu's own file of that name. See the 2026-08-16 regression below.

## Install

```bash
sudo cp etc/modprobe.d/zz-nvidia-power-fix.conf etc/modprobe.d/nvidia-runtimepm.conf /etc/modprobe.d/
sudo update-initramfs -u
# reboot
```

## Verify after reboot

```bash
cat /proc/driver/nvidia/params | grep DynamicPowerManagement   # expect: 0
cat /sys/bus/pci/devices/0000:01:00.0/power/control            # expect: on
journalctl -k -b | grep -c "Xid"                               # expect: 0
```

**Check the runtime value, not the conf file.** See the regression below.

## Regression, 2026-08-09

The conf file was still sitting in `/etc/modprobe.d/`, but it had not been in
effect for weeks:

```
/proc/driver/nvidia/params        DynamicPowerManagement: 2     <- should be 0
0000:01:00.0/power/control        auto                          <- should be on
```

Because `nvidia_drm modeset=1` is set, the nvidia modules are loaded from the
**initramfs**, which carries its own copy of `/etc/modprobe.d`. The conf file was
never baked in, so modprobe never read it. The 2026-07-25 upgrade to driver 595.84
regenerated the initramfs without it too.

Fix is just `sudo update-initramfs -u -k $(uname -r)`, but the lesson is that a
present conf file proves nothing here. Always read `/proc/driver/nvidia/params`.

## Regression, 2026-08-16 (the actual cause)

`DynamicPowerManagement: 2` was back, so the initramfs story above was only half
of it. `modprobe --showconfig | grep -i dynamicpower` gave the real answer:

```
options nvidia NVreg_DynamicPowerManagement=0x00      <- 99-nvidia-power-fix.conf
options nvidia "NVreg_DynamicPowerManagement=0x02"    <- /lib/modprobe.d/nvidia-runtimepm.conf
```

modprobe reads every `*.conf` from `/etc/modprobe.d`, `/run/modprobe.d` and
`/lib/modprobe.d` as one list sorted by **file name**, and for a repeated option
the **last** line wins. `99-...` sorts before `nvidia-...`, so Ubuntu's
gpu-manager file (regenerated on boot, owned by no package) won every time.

Two changes, either of which alone is enough:

* the fix was renamed `99-nvidia-power-fix.conf` -> `zz-nvidia-power-fix.conf`,
  so it is now the last file read;
* `/etc/modprobe.d/nvidia-runtimepm.conf` was added: a file of the same name in
  `/etc` shadows the one in `/lib` completely, in the running system and inside
  the initramfs alike (`mkinitramfs` copies both trees to their own paths).

Verify with `modprobe --showconfig | grep -i dynamicpower` (no `0x02` line may
remain), then after a reboot with `/proc/driver/nvidia/params`.

## HDMI audio function

`etc/udev/rules.d/90-nvidia-hdmi-audio-no-suspend.rules` pins the GPU's HDA
function `0000:01:00.1` to `power/control=on`. When that function runtime-suspends
it cannot report the HDMI ELD, and any monitor audio sink silently disappears from
PipeWire. Companion to the D3cold fix above.

```bash
sudo cp etc/udev/rules.d/90-nvidia-hdmi-audio-no-suspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```
