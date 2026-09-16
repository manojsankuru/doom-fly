#!/bin/bash
set -uo pipefail
pattern="python -m doom.server"
if ! pgrep -f "$pattern" >/dev/null; then
    echo "simulator is not running"
    exit 0
fi
pkill -TERM -f "$pattern"
echo "sent SIGTERM, waiting for a clean shutdown (up to 60 s)"
for second in $(seq 1 60); do
    if ! pgrep -f "$pattern" >/dev/null; then
        echo "simulator stopped cleanly after ${second} s"
        exit 0
    fi
    sleep 1
done
pkill -KILL -f "$pattern"
sleep 1
if pgrep -f "$pattern" >/dev/null; then
    echo "simulator is still running"
    exit 1
fi
echo "simulator did not stop within 60 s and was killed"
