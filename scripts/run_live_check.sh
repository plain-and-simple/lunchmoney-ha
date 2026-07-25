#!/usr/bin/env bash
# Boots a real Home Assistant against a throwaway config directory with this
# integration installed, then drives the real config flow against Lunch Money's
# public mock API. The pytest suite covers the same behaviour in-process; this
# proves the boot, storage and restart paths too, and needs no real credentials.
set -euo pipefail

cd "$(dirname "$0")/.."
CONFIG_DIR="${1:-$(mktemp -d)/haconfig}"

mkdir -p "$CONFIG_DIR/custom_components"
rm -rf "$CONFIG_DIR/custom_components/lunchmoney" "$CONFIG_DIR/.storage"
cp -R custom_components/lunchmoney "$CONFIG_DIR/custom_components/"

echo "▶ config dir: $CONFIG_DIR"
python scripts/live_check.py "$CONFIG_DIR"
