#!/bin/bash
# ONE-TIME CLEANUP: Remove local whisper + PyTorch from the VPS.
#
# The pipeline now uses the OpenAI Whisper API ($0.15/video) instead of
# the local model which pulled in ~3GB of PyTorch/CUDA dependencies and
# made the bot take 5+ minutes to start.
#
# Usage:  bash cleanup_whisper.sh
# After:  Delete this script — it's a one-time fix.

set -e

echo "=== Whisper + PyTorch Cleanup ==="
echo ""

# Find the right pip
if [ -x "$(dirname "$0")/../../venv/bin/pip" ]; then
    PIP="$(dirname "$0")/../../venv/bin/pip"
elif [ -x "$(dirname "$0")/venv/bin/pip" ]; then
    PIP="$(dirname "$0")/venv/bin/pip"
else
    PIP="pip3"
fi

echo "Using pip: $PIP"
echo ""

# Show what we're about to remove
echo "--- Packages to remove ---"
$PIP list 2>/dev/null | grep -iE "whisper|torch|nvidia|cuda|triton|tiktoken" || echo "(none found)"
echo ""

# Calculate space before
BEFORE=$(du -sh "$($PIP show openai-whisper 2>/dev/null | grep Location | cut -d' ' -f2)" 2>/dev/null | cut -f1 || echo "?")
echo "Site-packages size before: $BEFORE"
echo ""

# Uninstall in dependency order
echo "--- Uninstalling ---"
$PIP uninstall -y openai-whisper 2>/dev/null && echo "Removed: openai-whisper" || echo "openai-whisper not installed"
$PIP uninstall -y torch 2>/dev/null && echo "Removed: torch" || echo "torch not installed"
$PIP uninstall -y torchaudio 2>/dev/null && echo "Removed: torchaudio" || echo "torchaudio not installed"
$PIP uninstall -y torchvision 2>/dev/null && echo "Removed: torchvision" || echo "torchvision not installed"
$PIP uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl2 nvidia-nvjitlink-cu12 nvidia-nvtx-cu12 2>/dev/null && echo "Removed: nvidia CUDA packages" || echo "nvidia packages not installed"
$PIP uninstall -y triton 2>/dev/null && echo "Removed: triton" || echo "triton not installed"

echo ""
echo "--- Cleanup orphaned packages ---"
$PIP cache purge 2>/dev/null && echo "Pip cache purged" || true

echo ""
AFTER=$(du -sh "$($PIP show pip 2>/dev/null | grep Location | cut -d' ' -f2)" 2>/dev/null | cut -f1 || echo "?")
echo "Site-packages size after: $AFTER"
echo ""
echo "=== Done! Restart the bot: ==="
echo "  kill \$(cat /tmp/pipeline-bot.pid)"
echo "  # The healthcheck cron will auto-restart it in ~15 min,"
echo "  # or restart manually:"
echo "  cd $(dirname "$0") && nohup python3 pipeline_control.py > /tmp/pipeline-bot.log 2>&1 &"
