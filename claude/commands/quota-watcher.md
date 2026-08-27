---
description: Park every Claude before the 5h quota runs out and resume them after the reset, forever
argument-hint: "[PCT] [--rotate acct acct] | --stop | --status  (e.g. 5, or 10 --rotate eitan dad)"
allowed-tools: Bash(quota-watcher:*), Bash(claude-account:*), Bash(claude-limits:*)
---

`quota-watcher` is a systemd user timer that polls the 5-hour Claude limit every
minute and, when headroom runs low, asks every live Claude to park, forces it
after a grace period, and brings them all back when quota returns. It **loops
forever** — pause, resume, pause, resume — until `--stop`.

Current state:

!`quota-watcher --status`

Requested (may be empty): **$ARGUMENTS**

## What to do

Pass the arguments straight through to `quota-watcher` and report the result in
**one line**. Do not re-implement any of this in the session, do not poll the
quota yourself, and do not leave a loop running here — the timer is the loop.

- Empty, or a bare number → `quota-watcher <PCT>` (default 10). The number is
  the percent of quota **left**, not used: `5` means park at 5% remaining.
- `--rotate A B …` → pass it through unchanged. It only takes `claude-account`
  slot names; if one is unknown the command fails loudly and prints the saved
  ones, so just relay that. With rotation it does not sit and wait for the
  reset: it stops everyone, switches the machine to the next account with real
  headroom, and resumes them there — coming back round as each account frees up.
- `--stop` (or `stop`) → disarm. It also resumes anything still parked, so say
  how many came back. `--stop --leave-paused` disarms without waking them.
- `--status` / `--targets` → just run it and relay.

Other flags worth knowing, only if asked: `--grace SECONDS` (how long the polite
message gets before the forced stop, default 300), `--margin PCT` (headroom an
account needs before rotation switches into it, default 10), `--working-only`
(leave live-but-idle agents alone).

## Rules

- Arming is instant and safe; it parks nothing until the threshold is crossed.
- Never park or resume sessions by hand while it is armed — `claude-pause` and
  `claude-resume` share the same bookkeeping and you will fight it.
- If the user asks why a session stopped, read `~/.claude/quota-watcher/watcher.log`
  (and `courier.log` for whether the polite message actually landed) before
  guessing.
