---
description: Keep a project's no-reload dev server up until the PC shuts down, so every session tests against the same stable URL
argument-hint: <project> [port]  (e.g. surfstatus, or surfstatus 5300) | status | down <project> | logs <project>
allowed-tools: Bash(testbed:*), Bash(npm:*), Bash(curl:*), Read, Edit, Write, Grep, Glob
---

Put a codebase on a **testbed**: one long-lived dev server with hot reload
turned off, on a fixed port, that survives this session and only dies when the
machine shuts down or logs out. It is the consistent target we both test
against, instead of a fresh reloading server per session.

Registered projects right now:

!`testbed status`

Requested project (may be empty): **$ARGUMENTS**

## What to do

If the argument is `status`, `down …`, `logs …`, `restart …`, or `url …`, just
run `testbed <that>` and report the result in one line.

Otherwise the first argument is a project name (fuzzy is fine, `testbed`
resolves it by scanning `~/code`) and an optional second argument is a port.

**The port is optional and sticky.** Pass it straight through as the positional
port (`testbed up surfstatus 5300`) and it becomes that project's port from then
on. With no port given, do not invent one: `testbed` assigns a free port in
5300-5399 on first registration and reuses it forever after. Naming a port that
another project holds, or that some other process is using, fails loudly and
changes nothing, so just relay the error.

1. Run `testbed up <project> [port]`.
   - **Exit 0** means it is serving. Report the URL in one line and stop. Do
     not start any other dev server for this project for the rest of the
     session; use that URL for every check.
   - **Exit 2** means the project was not found. Ask which directory, then
     `testbed add <name> <path>` and retry.
   - **Exit 3** means setup is missing. Do step 2, then run `testbed up
     <project>` again.
   - No argument at all: show the table above and ask which project.

2. **First-time setup** (only when exit 3). `testbed doctor <project> --json`
   lists exactly what is missing under `needs`. Fix each one by hand, in the
   project's own style, mirroring the two projects that already have it:
   `~/code/MyProjects/SurfStatus` (mode `static`) and
   `~/code/MyProjects/Apeirion/apeirion-client` (mode `nohmr`). Read the
   relevant one first, then:

   - **Missing `dev:static` script** — add it to `package.json` next to `dev`,
     as the same dev server plus a distinct mode flag:
     `"dev:static": "vite --mode static"`. Do not change `dev`, `build`, or
     anything else. If the project's dev server is not vite, use whatever flag
     that server has for disabling live reload and say so in your report.
   - **HMR not disabled for that mode** — in `vite.config.*`, make the config a
     function of `{ mode }` if it is not already, and set
     `server.hmr: mode === '<mode>' ? false : undefined`. Leave every other
     option untouched, and add a short comment above it explaining that
     `npm run dev:static` serves without live reload so the page only changes
     when the user reloads it.
   - Optional, only for a vite project where the user cares about a page that
     never moves on its own: vite's client still calls `location.reload()` for
     a few events even with `hmr: false`. SurfStatus's `vite.config.ts` has a
     small `staticDev()` plugin that patches those out. Copy that pattern only
     if asked; plain `hmr: false` is the default.
   - `npm install` and port allocation are handled by `testbed up` itself.
     Never hand-roll a `vite` command or a background `npm run dev`.

3. Report in **one or two lines**: the URL, the port, and (if you set it up)
   which files you touched. Mention that a manual reload (Ctrl+R, or Shift+F5
   for a hard one) is how the page picks up new code, because that is the whole
   point of static mode.

## Rules

- `testbed` owns the lifetime. Never background a dev server yourself with `&`,
  `nohup`, or `setsid` for a project that has a testbed, and never kill the
  unit with `pkill`; use `testbed down <project>` / `testbed restart <project>`.
- A code change does **not** need a restart. Vite still recompiles on request,
  it just does not push the change to the browser. Only restart after editing
  `vite.config.*`, `package.json`, `.env*`, or installing dependencies.
- When something looks broken in the browser, read `testbed logs <project>`
  before theorising.
- The server is shared with the user, who may have that tab open right now.
  Do not stop or restart one you did not start without saying why first.
- Changing the port of a **running** server breaks the tab the user has open,
  because the URL moves. Only do it when they asked for that port in this
  message, and say the new URL in your reply. Never move a live server's port
  to try something out; use a throwaway project for that.
