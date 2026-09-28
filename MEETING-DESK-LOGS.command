#!/usr/bin/env bash
# Double-click in Finder: writes the last 400 API log lines to .api.log next to this file.
cd "$(dirname "$0")" && scripts/mac-launch.sh snapshot
