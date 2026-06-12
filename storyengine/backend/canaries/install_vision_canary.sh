#!/usr/bin/env bash
# Install/upgrade the vision-drift canary as USER systemd units (no root).
# Re-run after editing the unit files or canaries/vision_drift.py contracts.
# Requires: loginctl enable-linger clawd (already set on the VPS).
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$UNIT_DIR"
cp "$SRC_DIR/storyengine-vision-canary.service" \
   "$SRC_DIR/storyengine-vision-canary.timer" \
   "$SRC_DIR/storyengine-vision-canary-alert.service" \
   "$UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now storyengine-vision-canary.timer

echo "Installed. Next runs:"
systemctl --user list-timers storyengine-vision-canary.timer --no-pager
echo "Logs: journalctl --user -u storyengine-vision-canary -f"
