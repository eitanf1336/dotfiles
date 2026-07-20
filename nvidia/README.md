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

`etc/modprobe.d/99-nvidia-power-fix.conf`:

```
options nvidia NVreg_DynamicPowerManagement=0x00
```

`0x00` disables dynamic power management, so the GPU never enters D3cold and the
broken resume path is never taken. Costs a few watts at idle (matters on battery,
not while docked).

## Install

```bash
sudo cp etc/modprobe.d/99-nvidia-power-fix.conf /etc/modprobe.d/
sudo update-initramfs -u
# reboot
```

## Verify after reboot

```bash
cat /sys/bus/pci/devices/0000:01:00.0/power/control   # expect: on
journalctl -k -b | grep -c "Xid"                      # expect: 0
```
