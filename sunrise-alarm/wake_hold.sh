#!/bin/bash
# Runs as ROOT from sunrise-wake.service, right after the RTC wakes the machine.
# Its whole job is to stop the machine going straight back to sleep before the
# user's alarm timer fires.
#
# WHY THE RETRY LOOP: the RTC wake fires while systemd is still finishing the
# suspend operation, so a plain `systemd-inhibit` at that instant dies with
#   "Failed to inhibit: The operation inhibition has been requested for is
#    already running"
# and nothing holds the machine awake. logind then re-runs its lid handler a
# few seconds later and suspends again, straight through the alarm. That is
# exactly what happened on 2026-08-24 (woke 08:58:01, inhibit failed,
# re-suspended 08:58:07, slept through the 09:00 alarm). So we keep trying
# until the suspend operation has finished and the inhibitor takes.
#
# We block `sleep` AND `handle-lid-switch`, because the lid is usually still
# shut and the lid handler is what actually requests the second suspend.
HOLD="${1:-2700}"          # cover the whole sunrise + wake track, not just 10 min
DEADLINE=$((SECONDS + 60)) # keep retrying for up to a minute

log() { logger -t sunrise-wake "$*"; echo "sunrise-wake: $*"; }

while [ "$SECONDS" -lt "$DEADLINE" ]; do
  if systemd-inhibit --what=sleep:handle-lid-switch \
                     --who="sunrise-alarm" \
                     --why="alarm is about to fire" \
                     --mode=block \
                     /bin/sleep "$HOLD"; then
    log "held the machine awake for ${HOLD}s"
    exit 0
  fi
  sleep 0.5
done

log "ERROR: could not take a sleep inhibitor within 60s; alarm may be slept through"
exit 1
