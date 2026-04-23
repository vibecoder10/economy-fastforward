#!/bin/bash
# Install systemd unit for arq pipeline worker
set -euo pipefail

UNIT_FILE="/etc/systemd/system/storyengine-worker.service"

cat > "$UNIT_FILE" << 'EOF'
[Unit]
Description=StoryEngine arq Pipeline Worker
After=network.target redis.service

[Service]
Type=simple
User=clawd
WorkingDirectory=/home/clawd/projects/economy-fastforward/storyengine/backend
ExecStart=/home/clawd/.venv/bin/arq backend.worker.WorkerSettings
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/clawd/projects/economy-fastforward/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable storyengine-worker
systemctl restart storyengine-worker
echo "storyengine-worker installed and started"
