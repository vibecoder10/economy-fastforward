# Infrastructure & Deployment

## Production VPS

- Path: `/home/clawd/projects/economy-fastforward/`
- 8GB RAM + 4GB swap (for Remotion rendering)
- Auto-pulls from GitHub on every cron run (`git pull --ff-only`)

## Cron Schedule (US/Pacific)

| Time | Job | Timeout |
|------|-----|---------|
| 5:00 AM | `pipeline.py --discover` (idea discovery) | 10 min |
| 8:00 AM | `pipeline.py --run-queue` (process pipeline) | 4 hours |
| Every 15 min | `bot_healthcheck.sh` (restart Slack bot if dead) | - |
| Every 30 min | `approval_watcher.py` (check for approvals) | 10 min |

## Slack Bot Commands

`!status`, `!run`, `!update`, `!logs`, `!health`, `!queue`, `!approve`, `!reject`

## Rules

- Code pushed to `main` auto-deploys via the hourly `git pull --ff-only`. Don't push broken code to main.
- The Slack bot (`pipeline_control.py`) runs as a background process. PID tracked at `/tmp/pipeline-bot.pid`.
- Healthcheck auto-restarts the bot and sends Slack alert. Don't assume the bot is always running.
- All logs go to `/tmp/pipeline-*.log` on VPS. Reference these when debugging production issues.
