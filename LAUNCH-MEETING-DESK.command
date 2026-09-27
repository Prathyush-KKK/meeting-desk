#!/usr/bin/env bash
# Double-click in Finder (or run in a terminal): starts Meeting Desk for real on this Mac.
# Output also goes to .launch.log so it can be read without the Terminal window.
cd "$(dirname "$0")" && { echo "== $(date) =="; scripts/mac-launch.sh "$@"; echo "== exit $? =="; } 2>&1 | tee -a .launch.log
