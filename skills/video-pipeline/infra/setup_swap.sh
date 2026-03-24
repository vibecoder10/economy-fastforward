#!/bin/bash
# Setup 4GB swap file for Remotion rendering on 8GB VPS
# Run once with: sudo bash setup_swap.sh

set -e

SWAP_SIZE="4G"
SWAP_FILE="/swapfile"

# Check if swap already exists
if swapon --show | grep -q "$SWAP_FILE"; then
    echo "✅ Swap already active:"
    swapon --show
    free -h
    exit 0
fi

# Check if swapfile exists but isn't active
if [ -f "$SWAP_FILE" ]; then
    echo "Swapfile exists but not active, activating..."
    swapon "$SWAP_FILE"
    echo "✅ Swap activated"
    free -h
    exit 0
fi

echo "Creating ${SWAP_SIZE} swap file..."
fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
chmod 600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
swapon "$SWAP_FILE"

# Make persistent across reboots
if ! grep -q "$SWAP_FILE" /etc/fstab; then
    echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
    echo "Added to /etc/fstab for persistence"
fi

# Tune swappiness - only use swap under pressure
sysctl vm.swappiness=10
echo "vm.swappiness=10" >> /etc/sysctl.conf 2>/dev/null || true

echo ""
echo "✅ Swap setup complete:"
free -h
echo ""
echo "Swappiness set to 10 (only uses swap under memory pressure)"
