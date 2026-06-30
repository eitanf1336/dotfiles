---
name: privileged-run
description: >-
  Run root/sudo commands on the user's Linux desktop YOURSELF instead of asking
  them to paste commands. Use whenever a task needs privilege — apt/dpkg/package
  installs, systemctl, editing files under /etc, installing drivers/VPN clients,
  DKMS module builds, modprobe — and non-interactive sudo fails ("a terminal is
  required to authenticate" / "interactive authentication is required"). The
  trick is pkexec: it pops a graphical password dialog on the user's screen, so
  they authenticate there and you never see their password and they never paste
  a command. Use when the user says things like "just do it", "you do it", or is
  frustrated at being asked to run commands themselves.
---

# Run privileged commands yourself (via pkexec)

**Goal:** the user should never have to hand-type `sudo` commands when you can run
them. From Claude Code's Bash you have no controlling terminal, so plain `sudo`
can't prompt for a password and `sudo -v` doesn't help (its cached credential is
tty-bound and not shared with your non-TTY session). The answer is **`pkexec`**,
which authenticates through the desktop's polkit agent — a GUI password dialog
appears on the user's screen, they type the password there, and the command runs
as root. You never handle the password.

## When to use this

Any task that fails with one of these and needs root:

```
sudo: a terminal is required to authenticate
sudo: interactive authentication is required
sudo -n true   ->   fails
```

Examples: `apt install`, `dpkg -i`, `systemctl enable/start`, writing to `/etc`,
`modprobe`, DKMS builds, installing a VPN/driver, `update-grub`, etc.

## Preflight (one quick check)

pkexec needs a graphical session with a running polkit agent (GNOME Shell, KDE,
etc. provide one). Verify:

```bash
echo "session=$XDG_SESSION_TYPE display=${WAYLAND_DISPLAY:-$DISPLAY}"
which pkexec
pgrep -a -f 'polkit.*agent|gnome-shell|polkit-gnome|polkit-kde' | head -1
```

If `pkexec` exists and a shell/agent is running, you're good. If there is **no**
graphical session (pure SSH/headless), pkexec can't show a dialog — fall back to
giving the user a single copy-paste `sudo` one-liner.

## The recipe

Your Bash tool usually already inherits the session env, but export it explicitly
so pkexec can always reach the user's polkit agent (`id -u` is normally 1000):

```bash
U=$(id -u)
export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$U}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$U/bus}"

pkexec <the privileged command>
```

**Before you run it, tell the user in chat:** *"A password dialog will pop up on
your screen — type your password there to authorize it."* Then invoke the Bash
call with a **generous timeout** (e.g. 300000 ms): the call blocks until they
authenticate AND the command finishes (downloads, DKMS builds, etc.).

`pkexec` exit code `0` = success. `126` = user dismissed/failed the dialog (ask
them to retry). `127` = not authorized / no agent.

### Concrete examples

```bash
pkexec apt install -y /home/<user>/Downloads/Some_Agent.deb     # install a .deb
pkexec systemctl enable --now some.service                       # enable a service
echo 'net.ipv4.ip_forward=1' | pkexec tee /etc/sysctl.d/99-x.conf   # write to /etc
```

## Do it in ONE dialog, not ten

pkexec authenticates **per invocation** — each `pkexec` call = one password
dialog. For a multi-step privileged job, do **not** fire several `pkexec`
commands (the user gets dialog-spammed and the chain breaks if one is missed).
Instead write a small root script to a temp file and `pkexec` it **once**:

```bash
cat > "$CLAUDE_JOB_DIR/tmp/do-root.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
apt update
apt install -y net-tools traceroute
apt install -y /home/<user>/Downloads/Some_Agent.deb
systemctl enable --now some.service
EOF
chmod +x "$CLAUDE_JOB_DIR/tmp/do-root.sh"
pkexec bash "$CLAUDE_JOB_DIR/tmp/do-root.sh"     # single dialog for the whole job
```

## After it runs — verify

Confirm the result rather than trusting exit code alone, e.g. for a package:

```bash
dpkg -l <pkg> | tail -1
systemctl is-enabled <svc>; systemctl is-active <svc>
ls /usr/share/applications/ | grep -i <app>    # desktop launcher present?
```

## Gotchas

- Only use this for **legitimate admin tasks the user actually requested.** It's
  their machine and their explicit ask — you're saving them keystrokes, not
  escalating on your own.
- `pkexec` runs the target with a **clean root environment** (`$HOME=/root`, minimal
  PATH, no user env). Use absolute paths. To write files use `pkexec tee` /
  `pkexec install`, not shell redirection as the user.
- `apt` prints `WARNING: apt does not have a stable CLI interface` and
  `dpkg-preconfigure: unable to re-open stdin` under pkexec — both are harmless.
- Some DKMS modules log `BUILD_EXCLUSIVE ... does not match this kernel` and skip
  building. That's intentional when the feature is already in-kernel (e.g.
  WireGuard on kernel 5.6+); it is **not** an error.
- No graphical session at all → no dialog possible. Then, and only then, fall
  back to handing the user one clean single-line `sudo` command to paste.
```

This skill exists because the user was repeatedly asked to paste `sudo` lines to
install the Technion VPN (a Harmony SASE / Perimeter81 `.deb`); the right move was
`pkexec` from the start.
