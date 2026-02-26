#!/bin/bash
# Copy Robot/Optimus video assets from Desktop to remotion-video/public/
set -e

SRC_DIR="$HOME/Desktop/The Robot TRAP Nobody Sees Coming (A 4-Stage Monopoly)"
DEST_DIR="$(dirname "$0")/public"

mkdir -p "$DEST_DIR"

echo "Copying scene images..."
cp "$SRC_DIR"/Scene_*.png "$DEST_DIR/"
echo "  Copied $(ls "$DEST_DIR"/Scene_*.png | wc -l) images"

echo "Copying audio files..."
cp "$SRC_DIR"/Scene\ *.mp3 "$DEST_DIR/"
echo "  Copied $(ls "$DEST_DIR"/Scene\ *.mp3 | wc -l) audio files"

echo "Done! Assets are in $DEST_DIR"
