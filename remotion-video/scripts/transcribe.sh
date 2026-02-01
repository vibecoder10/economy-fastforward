#!/bin/bash
# Transcribe all scene audio files with word-level timestamps

cd "$(dirname "$0")/.."

mkdir -p src/captions

for i in {1..20}; do
  audio="public/Scene ${i}.mp3"
  output="src/captions/scene_${i}.json"
  
  if [ -f "$audio" ] && [ ! -f "$output" ]; then
    echo "Transcribing Scene $i..."
    uvx --from openai-whisper whisper "$audio" \
      --model tiny \
      --output_format json \
      --word_timestamps True \
      --output_dir src/captions
    
    # Rename output to expected format
    mv "src/captions/Scene ${i}.json" "$output" 2>/dev/null || true
  else
    echo "Skipping Scene $i (already exists or missing audio)"
  fi
done

echo "Done! Transcriptions saved to src/captions/"
