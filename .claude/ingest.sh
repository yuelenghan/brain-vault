#!/bin/sh
# brain-vault ingest - macOS/Linux wrapper for the cross-platform Python runner.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/ingest.py"
