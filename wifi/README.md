# WiFi disconnect fix (Intel AX201)

ASUS TUF Gaming F15 FX507ZV4, Intel Wi-Fi 6 AX201 160MHz (`8086:51f0`, CNVi),
driver `iwlwifi` / `iwlmvm`, firmware `89.123cf747.0`, kernel 7.0.0-22.

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
