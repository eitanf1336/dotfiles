---
description: Report this project's numbers into The Dashboard, or show what it knows
---

The Dashboard is the single place every project reports to. It lives at
`~/code/MyProjects/TheDashboard`, the app is `dashboard`, the reporting CLI is `dash`.

$ARGUMENTS

Do this:

1. Run `dash status` to see where things stand.
2. Work out what THIS project can report that The Dashboard does not already know:
   user counts, installs, revenue, expenses, testers' emails, a release, a milestone.
   Look at real sources (a console you can read, a log, the repo, a store page you
   were given), never at guesses.
3. Report it:
   - `dash metric <project> <metric> <value> [--date YYYY-MM-DD]`
   - `dash revenue <project> <amount> --source <where> --kind subscription|one_time`
   - `dash expense <amount> --vendor <who> --category ai|store|domain|hosting|service`
   - `dash user add <email> --project <project> --status lead|user|paying|tester`
   - `dash milestone <project> "<what happened>"`
4. If the project is missing entirely, add it with `dash project add ...`
   (`--track milestones` for anything non-commercial).
5. Say in one line what you reported.

The full protocol, the standard metric names and the JSON batch endpoint are in
`~/code/MyProjects/TheDashboard/WIRING.md`.
