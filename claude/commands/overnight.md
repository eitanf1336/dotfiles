---
description: See a group of Claude chats through to the end overnight - park, switch accounts, revive, never let one die
argument-hint: "[PCT] [--rotate acct acct] [chats…] | --status | --add <chat> | --stop"
allowed-tools: Bash(overnight:*), Bash(claude-account:*), Bash(claude-limits:*), Bash(quota-watcher:*)
---

`overnight` adopts a group of main Claude chats and is responsible for them
until every one has reported itself finished. A systemd timer ticks every
minute: it parks the group politely before the 5-hour quota runs out, forces it
after the grace period, rotates to another `claude-account` slot that really has
headroom (switching in, waking that slot's token and reading its LIVE limit
before trusting it), resumes everyone where they left off, and revives anything
that stopped, went idle or wedged. It ends on its own, with a report and a
WhatsApp message.

Current state:

!`overnight --status`

Requested (may be empty): **$ARGUMENTS**

## What to do

Pass the arguments straight through to `overnight` and report the result in
**one line**. Do not re-implement any of this in the session, do not poll the
quota yourself, and do not leave a loop running here — the timer is the loop.

- Empty → `overnight`. With nothing running that adopts every background chat
  that is *working* right now; with something already running it just shows the
  status.
- A bare number → the park threshold, percent of quota **LEFT** (default 12).
- Names/ids after it → adopt exactly those chats instead of the working set.
- `--rotate A B …` → account slots, in preference order. Unknown names fail
  loudly and print the saved ones; relay that.
- `--add <chat>` → hand it another chat mid-run. `--stop` → hand the group back
  (it wakes anything parked, writes the report and re-arms quota-watcher).

Other flags, only if asked: `--all-live` (also adopt idle chats), `--grace S`,
`--stall MIN` (idle before a nudge, 7), `--wedged MIN` (silent-but-alive before
a restart, 45), `--attempts N` (revivals before a chat is called stuck, 10),
`--jobs N` (concurrent revivals, 2 — each Claude is ~700MB), `--yolo`
(revivals skip permission prompts), `--quiet` (don't message the chats).

## Rules

- It tracks **main chats only**: top-level background sessions. Sub-agents live
  inside their parent and are never adopted. Interactive terminals are never
  adopted or killed either.
- Chats that start during the night are adopted automatically, including while
  the group is parked or the machine is between accounts.
- It stands quota-watcher down while it runs and re-arms it exactly as it was
  at the end. Never run both by hand, and never `claude-pause`/`claude-resume`
  a member while it is running — you will fight it.
- A chat ends its supervision only by making the last line of a reply
  `OVERNIGHT-DONE: <one sentence>`. Nothing else counts as finished.
- If asked why something stopped or restarted, read
  `~/.claude/overnight/overnight.log`, the per-chat logs in
  `~/.claude/overnight/logs/`, and `courier.log` for whether a message landed —
  before guessing.

## Hard-won rules (2026-09-01/02, the first real run)

Every line here was paid for. Do not undo one without reading why.

- **Wake a chat with `claude --resume <sid> -p`, never `--bg --resume`.**
  `--bg` mints a NEW session id on every wake: claude-c fills with duplicate
  entries under one name, and on a big transcript the fork came back empty once
  and a chat ran fifteen minutes with no history at all. Same session id, one
  conversation, always.
- **Never stop a chat he is attached to.** `claude attach <id>` is a real
  process (`pgrep -af "claude attach <id>"`), and stopping that chat drops his
  terminal back to the claude-c menu. Only when he is genuinely away: the
  sleep switch is on, or the desktop has been idle 15 minutes.
- **Read the quota with `--fresh` and `CLAUDE_LIMITS_TTL=0` after a switch,
  and wake the slot's token first.** claude-limits caches 90s and a switch
  takes 4, so a plain read hands back the OLD account's number under the new
  name. That wrote off an account with 97% free and parked the group for two
  hours.
- **A failed rotation must never leave the group parked.** If the account we
  are on can still run them, put them back to work here and retry later.
- **Hold an idle inhibitor for the whole run.** logind suspended the laptop at
  02:44 on its idle timer and ate ten hours. claude-keep-awake only holds while
  something is actively computing, and a supervised group is idle between turns
  constantly.
- **The park message must tell a chat to stop its sub-agents FIRST.** They
  spend the same quota and die with the parent anyway. Four Opus chats went
  10% -> 3% during a five minute grace window.
- **The trip point moves with the burn rate**, with a hard floor under it that
  skips the grace entirely. A flat percentage is not enough with several chats.
- **`jobs` caps revivals STARTED per tick**, not chats that happen to be
  working. Comparing it to the working count meant an idle chat sat 19 minutes
  unnudged with a 7 minute stall threshold.
- **Dedupe by name and reap duplicates every tick.** A resume can leave the old
  job registered and running: two agents, one repo, same history.
- **Adopt back a chat he gives more work to after it signed off.**
