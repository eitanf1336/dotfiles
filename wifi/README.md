# WiFi disconnect fix (Intel AX201)

ASUS TUF Gaming F15 FX507ZV4, Intel Wi-Fi 6 AX201 160MHz (`8086:51f0`, CNVi),
driver `iwlwifi` / `iwlmvm`, firmware `89.123cf747.0`, kernel 7.0.0-22.

## TL;DR

The disconnects are a **firmware crash**, not an RF or roaming problem:

```
iwlwifi 0000:00:14.3: Microcode SW error detected. Restarting 0x0.
0x00000034 | NMI_INTERRUPT_WDG
0x20000070 | NMI_INTERRUPT_LMAC_FATAL
```

Worked around with `disable_11ax=1`. The power-save and regdomain items below
were also real misconfigurations and are worth keeping, but they are **not** what
caused the drops. See "The actual cause" at the bottom.

## The problem

The laptop kept dropping its WiFi connection, most visibly on a multi-AP network
(a hotel with 5 APs sharing one SSID). The kernel log showed the card bouncing
between BSSIDs instead of handing off cleanly:

```
wlo1: disconnect from AP 88:dc:97:4a:58:61 for new auth to 88:dc:97:4a:58:62
```

Two actual misconfigurations were behind it.

### 1. WiFi power save was enabled

```
$ iw dev wlo1 get power_save
Power save: on
```

Forced by the Ubuntu default `/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf`:

```
[connection]
wifi.powersave = 3      # 3 = enable
```

With 802.11 power save on, the card sleeps between beacons. On AX201 this is the
single most common cause of random disconnects: the AP ages the station out or a
wake-up races an incoming frame, and the link drops. `iwlmvm power_scheme` was
also `2` (balanced), which lets the firmware honour those sleep requests.

### 2. Regulatory domain was unset (`00`)

```
$ iw reg get
global
country 00: DFS-UNSET
	(5170 - 5250 @ 80), (N/A, 20), AUTO-BW, PASSIVE-SCAN
	(5250 - 5330 @ 80), (N/A, 20), (0 ms), DFS, AUTO-BW, PASSIVE-SCAN
```

Under the world domain every 5GHz band is `PASSIVE-SCAN` only, so the card may
not send probe requests there. It has to wait to overhear a beacon before it can
consider an AP. On a single-AP home network that is survivable. With five
same-SSID APs it means the roaming logic is working half-blind, so it drops the
current AP before it has a usable candidate to move to. TX power is also capped
at 20dBm.

## The fix

`etc/NetworkManager/conf.d/zz-wifi-powersave-off.conf` turns power save off. The
filename matters: NetworkManager reads `conf.d` alphabetically and the last value
wins, so `zz-` beats the distro's `default-wifi-powersave-on.conf` without
touching a package-managed file.

```
[connection]
wifi.powersave = 2      # 2 = disable
```

`etc/modprobe.d/iwlwifi-stability.conf` pins the same policy at the driver level
and sets the correct regulatory domain:

```
options iwlmvm power_scheme=1              # 1 = CAM, always awake
options iwlwifi power_save=0 uapsd_disable=1
options cfg80211 ieee80211_regdom=IL
```

`power_scheme=1` and the regdom apply at module load, i.e. next boot. The
NetworkManager setting applies on `systemctl reload NetworkManager`, so the fix
takes effect immediately without a reboot.

Applied live at the time of the fix:

```bash
iw reg set IL
iw dev wlo1 set power_save off
systemctl reload NetworkManager
```

## Verifying

```bash
iw dev wlo1 get power_save     # want: Power save: off
iw reg get | grep ^country     # want: country IL: DFS-ETSI
```

Before: `Power save: on`, `country 00: DFS-UNSET`.
After: `Power save: off`, `country IL: DFS-ETSI`, 0% loss over a 30 min ping watch.

## The actual cause: a firmware watchdog crash

Disabling power save did not stop the disconnects. Roughly 25 minutes after that
fix went live, the link died again, and the kernel log showed why:

```
23:22:58  iwlwifi: Microcode SW error detected. Restarting 0x0.
23:22:58  iwlwifi: Loaded firmware version: 89.123cf747.0 so-a0-hr-b0-89.ucode
23:22:58  iwlwifi: 0x00000034 | NMI_INTERRUPT_WDG          <- LMAC watchdog fired
23:22:58  iwlwifi: 0x20000070 | NMI_INTERRUPT_LMAC_FATAL   <- UMAC fatal
23:23:02  wlo1: HW problem - can not stop rx aggregation for 88:dc:97:4a:58:62 tid 0
23:23:02  iwlwifi: Failed to trigger RX queues sync (-5)
23:23:02  wlo1: deauthenticating from 88:dc:97:4a:58:62 by local choice (Reason: 3)
```

The WiFi firmware hangs, its own watchdog kills it, and the driver tears the link
down to restart it. What makes it user-visible is what happens next:

```
23:23:47  device (wlo1): state change: activated -> failed (reason 'ip-config-unavailable')
23:23:47  Activation: failed for connection 'Nof Hotel'
```

DHCP can't complete against dead firmware, so after its 45s timeout
NetworkManager gives up and leaves the device **disconnected** rather than
retrying. That is why it presents as "the WiFi dropped and stayed down".

### It is venue-specific

Firmware asserts per boot (`grep -c "Microcode SW error"`):

| Boot | When | Asserts |
|---|---|---|
| -7 | Jul 21 14:41 - Jul 23 07:57 (home) | **0** |
| -6 | Jul 24 (hotel) | 46 |
| -4 | Jul 24 | 12 |
| -3 | Jul 24 | 18 |
| -2 | Jul 24 | 15 |
| -1 | Jul 24 | 9 |

Two days at home, zero crashes. Every crash is on the hotel network, whose APs
advertise three BSSIDs per radio (`88:dc:97:…`, `8E:dc:97:…`, `92:dc:97:…`) and
were carrying an HE (802.11ax) link. AX201 firmware asserting on HE +
multi-BSSID is a known interop failure.

### The workaround

Firmware 89 is already the newest present in `linux-firmware`
(`iwlwifi-so-a0-hr-b0-{72..89}.ucode.zst`), so there is no update to fix it with.
Falling back to 802.11ac avoids the crashing code path:

```
options iwlwifi power_save=0 uapsd_disable=1 disable_11ax=1
```

Applied without a reboot via `modprobe -r iwlwifi && modprobe iwlwifi`
(the `remove` directive in the distro's `iwlwifi.conf` unloads `iwlmvm` and
`mac80211` in the right order), then `systemctl restart NetworkManager`.

Cost: no 11ax rates. 11ac still gives ~866 Mbps on 5GHz, far more than a hotel
uplink provides.

### If it still crashes

Next levers, in order:

1. `bt_coex_active=0` — the AX201 is CNVi, so WiFi and Bluetooth share one radio;
   bad coexistence arbitration causes this same assert. Costs Bluetooth quality.
2. `11n_disable=8` — disables TX AMSDU, targeting the aggregation path that the
   `can not stop rx aggregation` messages point at.
3. Pull a newer `so-a0-hr-b0` ucode from the upstream linux-firmware git tree.

To confirm whether a given crash is this bug:
`journalctl -k -b -1 | grep -A5 "Microcode SW error"`.

## Notes

- `uapsd_disable=1` disables Unscheduled Automatic Power Save Delivery, another
  sleep mechanism that some APs implement badly. It is independent of the
  `power_scheme` knob.
- Changing `power_scheme` needs an `iwlwifi` module reload to take effect
  mid-session, which briefly drops the link. It was left to apply on the next
  boot instead, since the NetworkManager setting already stops mac80211 from
  requesting sleep.
- Cost of disabling power save: a small amount of extra idle battery drain from
  the WiFi radio. Worth it for a link that stays up.
