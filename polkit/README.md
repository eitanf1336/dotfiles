# polkit rules

System files here mirror their real paths under `/etc`. `install.sh` does **not**
copy them (it runs unprivileged), so install them by hand once per machine.

## 49-force-shutdown-ignore-inhibit.rules

**Symptom:** the GNOME power menu does nothing. You pick Restart or Power Off,
an app is "busy" so GNOME shows the *"some applications are still running"*
dialog, you click **Restart Anyway**, the dialog closes and the machine just
stays up.

**Cause (GNOME 50 / gnome-session-service 50.0):** whenever any app registers a
logout inhibitor, gnome-session-service holds a logind **block** inhibitor on
`shutdown` ("user session inhibited"). When you confirm, it calls logind's
`Reboot()` *without* asking to bypass inhibitors, so logind refuses because of
gnome-session's own lock:

```
gnome-session-service[…]: Shutdown failed: GDBus.Error:org.freedesktop.login1.BlockedByInhibitorLock: Operation denied due to active block inhibitor
```

Typical culprits: Text Editor with unsaved files, and Nautilus, which leaks a
"Moving Files" inhibitor that outlives the copy by days (`systemd-inhibit --list`
and `gdbus call --session --dest org.gnome.SessionManager --object-path
/org/gnome/SessionManager --method org.gnome.SessionManager.GetInhibitors` show
who is holding what).

**Fix:** `bin/power-menu-rescue` (systemd user unit `power-menu-rescue.service`)
watches for a confirmed restart/power-off followed by that exact logind refusal
and finishes the job with `systemctl reboot|poweroff -i`. That `-i` needs the
polkit actions `*-ignore-inhibit`, which default to `auth_admin_keep` (password
prompt) even for the active local session. This rule grants them to the active
local session for user `eitan` only.

Nothing else is loosened: the same user can already reboot without a password
(`org.freedesktop.login1.reboot` is `yes` for active sessions). The only thing
skipped is the "an app is busy" veto that the user just clicked through.

## Install

```sh
sudo install -m 0644 -o root -g root \
    polkit/etc/polkit-1/rules.d/49-force-shutdown-ignore-inhibit.rules \
    /etc/polkit-1/rules.d/
systemctl --user enable --now power-menu-rescue.service
```

polkitd picks up `rules.d` changes on its own, no reload needed. Verify with:

```sh
pkcheck --action-id org.freedesktop.login1.reboot-ignore-inhibit --process $$ && echo authorized
```
