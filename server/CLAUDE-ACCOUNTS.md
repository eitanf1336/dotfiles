# Claude accounts on the servers

Three laptop commands drive the `claude-account` that lives ON each server
(script: `bin/claude-account-servers`, the other two names are symlinks):

| command | runs on |
|---|---|
| `claude-account-little [args]` | little (`ssh little`, same entry as `ssh server`) |
| `claude-account-grandpa [args]` | grandpa (`ssh grandpa`) |
| `claude-account-servers [args]` | both, one after the other |

Every argument passes straight through, so it is the normal tool:
`list` (default), `whoami`, `use <name>`, `swap`, `save <name>`, `refresh <name>`,
`add <name>` (interactive login, per server only, not via `-servers`).

**Logins are never copied between machines.** Refresh tokens rotate; the same
login live on two machines logs one of them out. To give a server an account,
run `claude-account-<server> add <name>` and log in there.

## Activating grandpa (done 2 Oct 2026 except the login: step 2 Tailscale and step 5 wait on Eitan; the alias uses home WiFi for now)

Until these are done `claude-account-grandpa` just prints "not set up yet" and
`claude-account-servers` skips it.

1. Server installed on grandpa's NVMe (see the grandpa notes; wipe rules apply).
2. Tailscale up on grandpa; note its 100.x address.
3. Laptop `~/.ssh/config` gets:
   ```
   Host grandpa
       ControlMaster auto
       ControlPath ~/.ssh/cm-%r@%h:%p
       ControlPersist 10m
       ServerAliveInterval 15
       HostName <grandpa tailscale ip>
       User eitan
       IdentityFile ~/.ssh/id_ed25519_fleet
   ```
4. On grandpa: install Claude Code, and copy `bin/claude-account` and
   `bin/claude-status` from this repo into `~/.local/bin` (claude-account's
   `use` asks claude-status whether a chat is mid-task).
5. `claude-account-grandpa add <name>`, log in, then `claude-account-grandpa`
   should list it with usage.

That is all: no code change, the script finds the `grandpa` alias by itself.
