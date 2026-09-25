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
   Currently: 7777 Dashboard, 7790 PolyArena, 7800 ServerScreen, 8080 WhatsApp bridge, 8090 Whatclaude.
   The service is reachable at localhost, but its FILES and DB live on the server: read/change them with `ssh server`.
4. **Where work goes.** Long, unattended, overnight work: server. Anything touching his screen, browser,
   GPU, or laptop files: laptop. Renders: server by day, laptop only inside a blackout HE started (`farm`).
5. **Check before assuming.** `server` or `cat ~/.config/server-link/ports` tells you what moved.

## What runs where

**Server** (user units, linger on, `systemctl --user` on the server; copies of every unit file in
`~/code/linux-setup/server/systemd/`):
- PolyArena: `polyarena.service` (core, 127.0.0.1:7790), `polyarena-bot@*` (10 bots), `polyarena-contest.timer`.
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
- PolyArena daily: `polyarena-daily.timer` runs `bin/arena-daily` at 13:00 (live bots first, sleeps through the Claude limit and
  retries the same day). After each session `bin/arena-inbox` posts numbered `📊 Message N` items (passages, money asks, questions)
  to the "PolyArena" WhatsApp group; `polyarena-whatsapp.service` (a second bot.py, cwd PolyArena, guide WHATSAPP-LISTENER.md)
  answers him there. Its env file is `~/.config/polyarena-whatsapp/env` (system prompt + CWB_GROUP_JID).
- Bots first: `server-priority-guard.service` (bin/server-priority-guard). PolyArena units run at CPUWeight=1000 with
  MemoryLow (drop-ins in server/systemd/polyarena*.d). Every Blender gets CPUWeight=10, MemoryHigh=4G and OOM score 1000,
  ffmpeg gets nice 15, and when memory runs tight the guard FREEZES the newest render and thaws it when memory is easy again.
  A render that seems stuck may just be frozen: `systemctl --user list-units --state=frozen`, log `~/.local/state/server-priority-guard.log`.
- Internet watch: `server-netwatch.service` (bin/server-netwatch, unit in server/systemd) probes ping, DNS and Polymarket HTTPS every 15 s;
  after ~30 s down it pops a laptop notification, and on recovery says how long in My Claude (WhatsApp can't send mid-outage).
  Log `~/.local/state/server-netwatch.log`, outages in `server-netwatch-outages.log`.
- ServerScreen: `server-screen.service` (:7800) and the kiosk on the server's own display.
  Project stats reach it as: laptop `dashboard-laptop-push stats` (hourly; SurfStatus D1/KV via the laptop's wrangler, FocusRace Firebase; Eitan and tests dropped, rules in `TheDashboard/dashboard/collectors/projectstats.py`) -> `dash metric` on the server -> the screen reads The Dashboard (PolyArena money is the live P&L from :7790, never its Money War entries).
- Render farm: `cuteworld-farm.service` + the `farm` CLI (`farm day|night|status|queue|results`).
- Deed job: see `~/fleet-staging/deed-cutover.sh` (moves the deed chat, watcher, canary, push-limits and the
  deed login to the server; after it, `claude-c-deed` opens the deed board ON the server over ssh).

**Laptop**: claude-c and all chats, quota/account tools, creds-guard (main login), takeover/blackout,
dev testbeds, desktop tools, `server-link`, `server-chats-sync`, `server-claude-sync`, `wa-mirror`,
`learning-db-push`, `dashboard-laptop-push`, `server-screen-sync`.

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

## Plans, history, rollbacks

`~/fleet-staging/SERVER-PLAN.md` (the plan), `~/fleet-staging/PROGRESS.md` (what moved, with rollbacks),
`~/fleet-staging/*-cutover.sh` / `*-rollback.sh`.
