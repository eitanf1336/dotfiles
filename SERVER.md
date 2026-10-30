# Working with eitan-vivobook-server (read this before touching anything that runs 24/7)

Eitan has two Linux machines on one Tailscale network:

| | laptop `eitan-u` | server `eitan-vivobook-server` |
|---|---|---|
| role | where he works: chats, claude-c, screens, GPU, all code editing | runs 24/7, lid closed or showing its screen; always-on and long jobs |
| reach | `ssh laptop` (from the server; Tailscale only, key only) | `ssh server` (key auth, NOPASSWD sudo), `ssh server-lan` (home WiFi) |
| Tailscale | 100.110.61.68 | 100.85.207.11 |

`server` on the laptop: `server` (health + services), `server logs <unit>`, `server restart <unit>`,
`server run <cmd>`, `server ssh`, `server link` (port forwards).

## The five rules

1. **Code lives on the laptop.** The server runs rsynced copies at the SAME paths (`/home/eitan/...`).
   Never edit code on the server; edit here, then deploy (below). Venvs are never copied: rebuild on the
   server with `uv` (python 3.12 via `uv python install 3.12`).
2. **One owner per thing.** A service, the WhatsApp session, the PolyArena wallet, a Claude login: exactly
   ONE machine runs it. The other machine's copy stays `disable`d (or `mask`ed) as a rollback. Never start both.
3. **localhost keeps working.** `server-link.service` (laptop) forwards every port listed in
   `~/.config/server-link/ports` from laptop `127.0.0.1:PORT` to the server's `127.0.0.1:PORT`.
   Currently: 7777 Dashboard, 7790 PolyArena, 7800 ServerScreen, 7830 Technion VPN screen (noVNC), 8080 WhatsApp bridge, 8090 Whatclaude.
   The service is reachable at localhost, but its FILES and DB live on the server: read/change them with `ssh server`.
4. **Where work goes.** Long, unattended, overnight work: server. Anything touching his screen, browser,
   GPU, or laptop files: laptop. Renders: server by day, laptop only inside a blackout HE started (`farm`).
5. **Check before assuming.** `server` or `cat ~/.config/server-link/ports` tells you what moved.

## What runs where

**Server** (user units, linger on, `systemctl --user` on the server; copies of every unit file in
`~/code/linux-setup/server/systemd/`):
- PolyArena (CLOSED 4 Oct 2026, every unit disabled, never restart): `polyarena.service` (core, 127.0.0.1:7790), `polyarena-bot@*` (10 bots), `polyarena-contest.timer`.
  **After ANY core restart the wallet is locked**: Eitan runs `~/code/MyProjects/PolyArena/bin/arena-wallet unlock`
  on the LAPTOP (zenity popup; `ARENA_SHOW_PASS=1` shows what he types). Never restart the core without his yes.
  Fable wakes run on the server (`ssh server`, then `bin/arena wake ...` in the repo), only on his word.
- The Dashboard: `the-dashboard.service` (:7777), sync and marketing timers, `advertising-post-stats.timer`.
  `dash` on the laptop is a wrapper that runs on the server (spools offline). Devstats, Cloudflare token and
  Ko-fi/credential files are pushed hourly from the laptop by `dashboard-laptop-push.timer`.
- WhatsApp: `whatsapp-bridge` (127.0.0.1:8080), `claude-whatsapp` (My Claude bot), `claude-whatsapp-monitor`,
  `whatclaude` (:8090), doctor/assist timers, `surf-report.timer`, `ai-detect-*` timers.
  The laptop has a READ-ONLY mirror of messages.db (`wa-mirror.timer`, ~30 s lag) and a guard file
  `~/.config/whatsapp-claude/REMOTE` that stops any laptop bridge from starting. Never start a bridge on the laptop.
- PolyArena daily: `polyarena-daily.timer` runs `bin/arena-daily` at 05:00 (first run: one-off polyarena-daily-once.timer, 26 Sep 11:00) (live bots first, sleeps through the Claude limit and
  retries the same day). After each session `bin/arena-inbox` posts numbered `📊 Message N` items (passages, money asks, questions)
  to the "PolyArena" WhatsApp group; `polyarena-whatsapp.service` (a second bot.py, cwd PolyArena, guide WHATSAPP-LISTENER.md)
  answers him there. Its env file is `~/.config/polyarena-whatsapp/env` (system prompt + CWB_GROUP_JID).
- PolyArena self-check: `bin/arena-selfcheck` runs daily right after the 05:00 wakes finish (`OnSuccess=`/`OnFailure=` on `polyarena-daily.service`; `polyarena-selfcheck.timer` is a 12:00 fallback, skipped if today's report exists) (read only): coverage of the real venue (the 30 Sep bug: core saw 40k of 233k markets), feed freshness, accounting and sim-exchange invariants, the live wallet, bots, wakes, services, disk, and the pytest suite. One line per check in `data/selfcheck/YYYY-MM-DD.md`, a short verdict to the "PolyArena" group, exit 1 (unit failed) on any FAIL. `--no-post` / `--quick` / `--only feed,live` for manual runs; log `data/logs/selfcheck.log`.
- PolyArena deals: `polyarena-deals.timer` runs `bin/arena-deals check` every 10 min: Eitan's deals/ultimatums live in `deals.json` (DEALS.md is generated), fired state in `data/deals-state.json` (never rsync over it). On fire it words the bot and posts a numbered group message with the commands; it never moves money or cuts a bot.
- PolyArena hunt (4 Oct): `polyarena-hunt.timer` runs `bin/arena-hunt tick` hourly at :20 (the gate: hunter corners move board, tape, sim 48 h, live $25, scale by numbers only; it moves pool money itself, inside $300 and the real wallet cash; live corner down 20% = real orders cancelled, money back to the pool, back to sim; $15 wallet loss in a day freezes trials 24 h). State `data/hunt/state.json` (never rsync over it), log `data/hunt/log.md` + `data/logs/hunt.log`. Corner accounts are `<fable>-cN` (sim) and `<fable>-cN-lK` (live), dirs with LAB_OF so no wake touches them. `polyarena-hunt-pm.timer` (15:00) is the afternoon hunter wake, gated by PolyArena's 15% Claude budget (`bin/arena-hunt quota`; it asks in the group before cutting anything, answers via `bin/arena-hunt quota-answer`). One hunt line a day to the group at 21:00.
- Bots first: `server-priority-guard.service` (bin/server-priority-guard). PolyArena units run at CPUWeight=1000 with
  MemoryLow (drop-ins in server/systemd/polyarena*.d). Every Blender gets CPUWeight=10, MemoryHigh=4G and OOM score 1000,
  ffmpeg gets nice 15, and when memory runs tight the guard FREEZES the newest render and thaws it when memory is easy again.
  A render that seems stuck may just be frozen: `systemctl --user list-units --state=frozen`, log `~/.local/state/server-priority-guard.log`.
- Internet watch: `server-netwatch.service` (bin/server-netwatch, unit in server/systemd) probes ping, DNS and Polymarket HTTPS every 15 s;
  after ~30 s down it pops a laptop notification, and on recovery says how long in My Claude (WhatsApp can't send mid-outage).
  Log `~/.local/state/server-netwatch.log`, outages in `server-netwatch-outages.log`.
- ServerScreen: `server-screen.service` (:7800) and the kiosk on the server's own display.
  Project stats reach it as: laptop `dashboard-laptop-push stats` (hourly; SurfStatus D1/KV via the laptop's wrangler, FocusRace Firebase; Eitan and tests dropped, rules in `TheDashboard/dashboard/collectors/projectstats.py`) -> `dash metric` on the server -> the screen reads The Dashboard. PolyArena was closed on 4 Oct 2026 and is gone from the screen and its money.
- Technion VPN jump host (29 Oct 2026): the Perimeter81 / Harmony SASE app holds the VPN login on the server (the ONLY owner: the laptop app stays disconnected); `ssh srv3` on the laptop hops through it. Full tunnel: all server traffic exits via Technion. See "Technion VPN jump host" below.
- Render farm: `cuteworld-farm.service` + the `farm` CLI (`farm day|night|status|queue|results`).
- Apeirion launch recorder: `apeirion-launchrec.service` (scheduler, `launchwatch.mjs`) starts a transient `launchrec-<T0>-<id8>`
  unit 20 min before every SpaceX T-0: headless Chrome (Iris Xe, ANGLE gl-egl) films the live Apeirion page, `edit.py` cuts an
  X post package, rsynced to the laptop `~/Videos/Launch Posts/`. One Chrome at a time; never posts. Code in
  `apeirion-client/scripts/live-timelapse/` (dist copy at `apeirion-client/dist`), data `~/launch-recorder-data/`.
- Deed job: see `~/fleet-staging/deed-cutover.sh` (moves the deed chat, watcher, canary, push-limits and the
  deed login to the server; after it, `claude-c-deed` opens the deed board ON the server over ssh).

**Laptop**: claude-c and all chats, quota/account tools, creds-guard (main login), takeover/blackout,
dev testbeds, desktop tools, `server-link`, `server-chats-sync`, `server-claude-sync`, `wa-mirror`,
`learning-db-push`, `dashboard-laptop-push`, `server-screen-sync`.

## Technion VPN jump host

srv3 (132.68.161.39) is reachable only over the Technion VPN (Check Point "Harmony SASE", formerly Perimeter81).
Technion WiFi blocks the VPN and the phone hotspot is unusable, so the VPN login lives on the SERVER and the
laptop reaches srv3 through it. Connected for the first time 29 Oct 2026 23:21.

- **ONE OWNER: the server.** The laptop's Perimeter81 app stays installed (rollback) but must stay
  DISCONNECTED from now on. Never connect both.
- **What runs** (user units on the server, copies in `server/systemd/vpn-*`):
  `vpn-xvfb` (virtual display :81, 1280x800), `vpn-wm` (openbox), `vpn-vnc` (x11vnc on 127.0.0.1:5981, no password,
  localhost only), `vpn-novnc` (websockify + noVNC on **127.0.0.1:7830**), `vpn-p81` (the app,
  `/opt/Perimeter81/perimeter81`, same 10.0.3.933 .deb as the laptop, `~/Downloads/Perimeter81_10.0.3.933.deb`),
  `vpn-watch.timer` (every 2 min, `server/bin/vpn-watch` -> server `~/bin/vpn-watch`), and the root
  `perimeter81helper.service` from the package.
- **The screen**: http://localhost:7830 on the laptop (server-link port) shows display :81 in a browser tab.
- **The login** (the workspace is on the EU region; the US page `technion.perimeter81.com` says the account is
  "not activated" and rejects the password):
  https://technion.eu.sase.checkpoint.com/sign-in?redirectUrl=perimeter81://eu.sase.checkpoint.com/callback
  -> "Sign in with Microsoft" (Technion SSO, login.microsoftonline.com/technion.ac.il) ->
  `eitanfrenkel@campus.technion.ac.il` + his Technion password -> Microsoft Authenticator number match on his
  phone ("Don't ask again for 30 days" ticked 29 Oct, so MFA is skipped until about 28 Nov 2026) -> Chrome's
  "Open Perimeter81?" ("Always allow" ticked) -> Connect in the app, network **Technion-Users**.
- **Re-login is automatic, phone-free (30 Oct 2026)**: `server/bin/vpn-relogin` (server `~/bin/vpn-relogin`, run by
  vpn-watch at most once per 15 min, or by hand `ssh server vpn-relogin`) opens the EU page, clicks Sign in with
  Microsoft, then hands the Microsoft pages to `vpn-mslogin`, which reads them through Chrome's localhost debugging
  port 9333 (`vpn-cdp.js`, the port is set in `vpn-xdg-open`) and walks: account picker -> password (Chrome's saved
  one, filled by a real click, Enter) -> "Approve sign in request" -> "I can't use my Authenticator" -> "Use a
  verification code" -> the 6-digit code from `vpn-totp` -> "Stay signed in" Yes. Then the app's token arrives and
  it clicks Connect. The 30-day "don't ask again" tick did NOT hold (Technion forces a fresh sign-in; 29 Oct night
  it asked again at 07:26 next morning), hence the code method. If anything is off it exits 5 and vpn-watch sends
  "Technion VPN needs you ... Open localhost:7830" (laptop popup + My Claude WhatsApp, once per outage, reminder
  every 2 h). Screenshots of each run in `~/.local/state/vpn-relogin/`. TESTED end to end 30 Oct 2026 18:45 (laptop time) on the first real drop: the
  walker had stalled on the "Verify your identity" option list because Microsoft's tiles ignore a synthetic .click();
  click_text now does a real xdotool click at the element (fallback .click()); re-login then took 3 minutes, no phone.
- **The code authenticator**: a second "authenticator app" method on his Microsoft account (added 30 Oct 2026 09:28,
  one phone tap of his). Its secret exists only on the server, sealed by `systemd-creds encrypt --user` into
  `~/.config/vpn-jump/totp.cred` (bound to that machine's key: a copied file decrypts nowhere else; no plain copy
  anywhere, never printed). `vpn-totp` prints the current code; `vpn-totp-store <file>` seals a new secret.
  Default sign-in method is still "notification", so his phone also buzzes at each server login; he can switch it
  to "code" himself at mysignins.microsoft.com/security-info (Kit's classifier refused that account change).
  Security cost, said plainly: the server now holds both factors (Chrome's password store + the sealed code secret),
  so root on the server equals his Technion login; the server is Tailscale-only with key auth.
- **The password lives only in Chrome's own password manager** in the dedicated profile
  `~/.local/share/vpn-jump/chrome-profile` (Chrome stores it encrypted with `--password-store=basic`; no plain file,
  never printed; protection is the server account's file permissions). It is saved by clicking Save on Chrome's
  "Save password?" bubble at a human login; after that the Microsoft page autofills it.
- **Login browser**: the app's links open through `server/bin/vpn-xdg-open` (server
  `~/.local/share/vpn-jump/bin/xdg-open`, first on vpn-p81's PATH): Google Chrome stable (official .deb,
  `/opt/google/chrome`, updates via Google's apt repo) with that profile. It hands `perimeter81://` callbacks
  straight to the app and logs only scheme://host/path (callbacks carry tokens). Fallbacks in the wrapper:
  Playwright's Chrome for Testing, then the snap Chromium (which cannot pass the callback on).
  Note the app's own "Sign In" button opens the US page; use the EU URL above instead.
- **App settings** (gear, bottom left): Connect on launch, Always-On VPN, Automatic Wi-Fi Security, Trusted
  Wi-Fi, notifications and Automatic Updates are all "Set by Admin"; there is no auto-reconnect switch in the UI
  (its policy value is off). Token lifetimes: access 8 h / 16 h, refresh 24 h / 14.6 days,
  `sessionExpirationPreferredTime` 03:00. vpn-watch + vpn-relogin stand in for auto-reconnect.
- **The tunnel is FULL** on this network: `0.0.0.0/1` + `128.0.0.0/1 dev p81` (tunnel address 10.250.88.x), so
  ALL the server's internet leaves through Technion's gateway in Israel (public IP 212.59.64.200), not just
  132.68.0.0/16. Tailscale keeps working. vpn-watch checks `ip route get 132.68.161.39` says `dev p81` plus a
  TCP connect to srv3:22.
- **DNS trap**: the helper DNATs ALL outgoing DNS to its proxy on 127.0.0.1:5354, which answers SERVFAIL while
  logged out; on 29 Oct 2026 that broke DNS for the whole server the moment the package was installed.
  `vpn-watch` keeps three nat OUTPUT RETURN rules (systemd-resolve's own queries, and anything to 127.0.0.0/8)
  above that DNAT, re-adding them after a reboot (timer fires 15 s after boot). Check: `sudo iptables -t nat -S OUTPUT`.
- **Laptop side**: `~/.ssh/config` has `Match originalhost srv3 !exec "ip route get 132.68.161.39 2>/dev/null | grep -q ' dev p81 '"`
  -> `ProxyJump server`: direct if the LAPTOP's own VPN carries srv3, through the server otherwise. The srv3 key
  stays on the laptop (passphrase + agent); the server only forwards TCP. 29 Oct: `ssh srv3` 1.1 s, 10 MB in 1.9 s.
- **Rollback** (laptop owns the VPN again): on the server
  `touch ~/.config/vpn-jump/off; systemctl --user disable --now vpn-p81 vpn-watch.timer` (Disconnect and sign out
  in the app first, through localhost:7830), then connect the laptop's Perimeter81 app (EU workspace, Microsoft
  sign-in). Never have both connected at once. Forward again: `rm ~/.config/vpn-jump/off;
  systemctl --user enable --now vpn-p81 vpn-watch.timer`, then `ssh server vpn-relogin`.
- Logs: `~/.local/state/vpn-jump.log` (watch, relogin, redacted xdg-open lines) on the server; the app's own log is
  `~/.config/Perimeter81/logs/gui.log`.

## Deploying a code change to something that runs on the server

1. Edit and commit on the laptop.
2. `rsync -a --exclude .git --exclude .venv --exclude __pycache__ <repo>/ server:<same path>/`
   (never `--delete` a data dir; exclude the project's data/ and state files).
3. If dependencies changed: `ssh server 'cd <repo> && uv pip sync ...'` (or rebuild its venv).
4. `server restart <unit>` and check `server logs <unit>`. (PolyArena core: only with his yes.)

## Adding a NEW always-on service to the server (checklist, all of it)

1. Unit file on the server in `~/.config/systemd/user/`, with
   `Environment=PATH=%h/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin` if it runs claude/uv/node, and
   `After=network-online.target` + `Wants=network-online.target` if it fetches anything (the server boots
   before WiFi is up; a collector that caches a failed fetch will show empty data until restart).
2. Bind to `127.0.0.1`. If the laptop needs it, append the port to `~/.config/server-link/ports` and
   `systemctl --user restart server-link` (the port must be FREE on the laptop first).
3. Copy the unit into `~/code/linux-setup/server/systemd/` and commit (the server must be rebuildable).
4. If a laptop copy existed: `systemctl --user disable --now` it there (rule 2).
5. **ServerScreen** (the server's own screen) lists running user services with CPU/RAM automatically in its
   SERVER panel; if yours is noise, add it to `HIDE_UNITS` in `~/code/MyProjects/ServerScreen/server.py`.
   If it is a PROJECT (has users or money), make sure its numbers reach The Dashboard (`dash ...`) and money
   reaches the Dashboard revenue table or the Money War (`contest`), because the screen reads only those;
   a new project scene is added in `ServerScreen/web/index.html` + `server.py` (real numbers only: real people,
   real users, real money; never page views or internal counters; every project leads with money earned).
   Deploy ServerScreen like any project and `ssh server 'systemctl --user restart server-screen'`.
   Its bottom-right "Running now" list shows every project with one live word (auto from services and
   `claude agents`; add auto rules in `AUTO_NOW` in server.py). Any Claude sets its own word with
   `server-now <project> <word> [detail] [--ttl 2h]` / `--clear` (POST :7800/api/now, works from the laptop too).
6. Report: `dash milestone fleet "<what moved>"`, and a line in `~/fleet-staging/PROGRESS.md`.
7. Anything that pops a GUI (`notify-send`, `zenity`) on the server is forwarded to the laptop screen
   through `~/bin/laptop-gui` symlinks; don't rely on it for anything critical, alert via WhatsApp instead.

## Claude on the server

- It uses a COPY of the laptop's main login (his choice). If either machine suddenly demands `/login`,
  re-copy: `scp ~/.claude/.credentials.json server:.claude/` (or the reverse, whichever still works).
- `server-claude-sync.timer` (every 5 min) copies CLAUDE.md, settings, skills, commands, prompts, statusline
  and Kit to the server and syncs memory both ways, so server Claudes follow the same rules.
- Server chats appear on the claude-c board as `[srv]`; `n` then `s` starts one on the server; Enter attaches
  over ssh; Ctrl+Z detaches and it keeps running; `B` reopens a chat with permission checks off.

## The server's screen

tty1 autologins and runs `~/bin/server-kiosk` (cage + chromium kiosk on http://127.0.0.1:7800).
Keys on the server's keyboard: `b` sleep/wake (backlight), `←` `→` previous/next slide, nothing else.
Ctrl+Alt+F2 gives a normal console. Disable the kiosk with
`touch ~/.config/server-kiosk-off` on the server.
`kiosk-watchdog.timer` (every minute, code in `ServerScreen/bin/kiosk-watchdog`) kills cage when the page has not called
server.py for 3 min (chromium's renderer wedged for 5 days once, 11 to 16 Oct 2026); tty1 then relogs and restarts the kiosk. Log `~/.local/state/kiosk-watchdog.log`.

## grandpa (the second server)

Late grandpa Chaim's ThinkPad E570 (GTX 950M), Ubuntu 26.04 on its NVMe since 2 Oct 2026.
- Reach it: `ssh grandpa` (laptop `~/.ssh/config`: user eitan, key `~/.ssh/id_ed25519_fleet`, NOPASSWD sudo,
  `HostKeyAlias grandpa`). Today that is home WiFi `192.168.68.69` (DHCP, may move: find it with
  `nmap -p22 --open 192.168.68.0/22` and `ssh -i ~/.ssh/id_ed25519_fleet eitan@<ip> hostname`).
  Tailscale is installed but logged out; after `sudo tailscale up --hostname grandpa` switch HostName to its 100.x IP.
- Claude: `claude-account-grandpa [list|whoami|use|add <name>]` (`~/.local/bin/claude` + claude-account there).
- Runs: the backup of its 1 TB disk to Drive (system units `grandpa-pack`, `grandpa-stallguard`, logs in
  `~/grandpa/logs/main.log`). The 1 TB WD disk (`/dev/sda`, serial WD-WXM1A5731ZTT) holds his files: kernel
  read-only (`hdd-readonly.service`) and mounted ro at /mnt/data. NEVER write to it or wipe it.
- Screen: little's ServerScreen half a cycle ahead (`?role=grandpa`, tunnel `grandpa-screen-tunnel`), with its own
  SERVER panel and Running now list from a local `server-screen-local` (:7801). Files: `server/grandpa/`.
  `kiosk-watchdog.timer` there runs `kiosk-watchdog grandpa` (same 3 min rule, watches the grandpa role).

## Plans, history, rollbacks

`~/fleet-staging/SERVER-PLAN.md` (the plan), `~/fleet-staging/PROGRESS.md` (what moved, with rollbacks),
`~/fleet-staging/*-cutover.sh` / `*-rollback.sh`.

- **/tmp scratch cleanup (26 Sep 2026):** server crontab entry `# claude-scratch-clean` deletes files older than 2 h under /tmp/claude-1000/*MinecraftArena-runs* every hour (xx:17). /tmp is tmpfs, and the arena bots' headless claude sessions leaked 2.5 GB of cached camera frames into RAM. The Minecraft chat confirmed nothing reads them after a chapter (15-25 min).
- **zram swappiness 180 (26 Sep 2026):** /etc/sysctl.d/99-zram-swappiness.conf on the server so idle pages compress into the 7.7 GB zram before renders get frozen. Undo: delete the file and `sudo sysctl vm.swappiness=60`.
- **Root reserve 5% -> 2% (29 Oct 2026):** the server's disk hit 100% (0 bytes free for user services; MinecraftArena alone is 106 GB, `runs/` 68 GB) while installing the VPN jump host. `sudo tune2fs -m 2 /dev/nvme0n1p2` freed ~7 GB for users without deleting anything. Undo: `sudo tune2fs -m 5 /dev/nvme0n1p2`. The real fix is clearing old MinecraftArena runs/out (his call).
