#!/usr/bin/env bash
# Run one job politely on the shared DGX:  bash scripts/dgx/guard.sh <name> <command...>
# - waits until MemAvailable >= MIN_FREE_GB (default 30) before starting
# - runs the job in its own process group with nice/ionice and capped CPU threads
# - kills ONLY this job's process group if MemAvailable drops below KILL_FREE_GB (default 12)
# Log: logs/<name>.log, pid: logs/<name>.pid, exit status: logs/<name>.status
set -u
cd "$(dirname "$0")/../.."
name="$1"; shift
MIN_FREE_GB="${MIN_FREE_GB:-30}"
KILL_FREE_GB="${KILL_FREE_GB:-12}"
THREADS="${THREADS:-4}"
mkdir -p logs
log="logs/$name.log"
avail_gb() { awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo; }
while [ "$(avail_gb)" -lt "$MIN_FREE_GB" ]; do
  echo "$(date '+%F %T') waiting: MemAvailable $(avail_gb) GB < $MIN_FREE_GB GB" >> "$log"
  sleep 120
done
echo "$(date '+%F %T') start ($(avail_gb) GB free): $*" >> "$log"
export OMP_NUM_THREADS="$THREADS" MKL_NUM_THREADS="$THREADS" OPENBLAS_NUM_THREADS="$THREADS" NUMEXPR_MAX_THREADS="$THREADS"
setsid nice -n 10 ionice -c3 "$@" >> "$log" 2>&1 &
pid=$!
echo "$pid" > "logs/$name.pid"
status=""
while kill -0 "$pid" 2>/dev/null; do
  if [ "$(avail_gb)" -lt "$KILL_FREE_GB" ]; then
    echo "$(date '+%F %T') WATCHDOG: MemAvailable $(avail_gb) GB < $KILL_FREE_GB GB, stopping this job" >> "$log"
    kill -TERM -- "-$pid" 2>/dev/null; sleep 20; kill -KILL -- "-$pid" 2>/dev/null
    status=99
    break
  fi
  sleep 30
done
if [ -z "$status" ]; then wait "$pid"; status=$?; fi
echo "$(date '+%F %T') end status $status" >> "$log"
echo "$status" > "logs/$name.status"
exit "$status"
