# Infrastructure & Deployment

## Production VPS

- Path: `/home/clawd/projects/economy-fastforward/`
- 8GB RAM + 4GB swap (for Remotion rendering)
- Auto-pulls from GitHub on every cron run (`git pull --ff-only`)

## Cron Schedule (US/Pacific)

| Time | Job | Timeout |
|------|-----|---------|
| 5:00 AM | `osiris.competitor_scraper` (scrape competitor videos) | 10 min |
| 5:30 AM | `pipeline.py --competitors` (competitor channel scraper) | 10 min |
| **6:30 AM** | **`autopilot --check-cycle` (autopilot decision cycle)** | 15 min |
| 7:00 AM | `performance_tracker.py --recent` (YouTube metrics sync) | 10 min |
| **7:30 AM** | **`autopilot.ctr_monitor` (CTR monitoring)** | 10 min |
| 8:00 AM | `pipeline.py --run-queue` (process pipeline) | 4 hours |
| **8:30 AM** | **`autopilot.learning_extractor` (extract learnings)** | 10 min |
| 9:00 AM | `pipeline.py --discover` (idea discovery) | 10 min |
| Every 15 min | `bot_healthcheck.sh` (restart Slack bot if dead) | - |
| Every 30 min | `approval_watcher.py` (check for approvals) | 10 min |

**Bold = Autopilot jobs (added March 2026)** — sequenced to run before/after related jobs

## Slack Bot Commands

`!status`, `!run`, `!update`, `!logs`, `!health`, `!queue`, `!approve`, `!reject`, `competitors`

### Autopilot Commands (NEW)
```
autopilot on              # Enable autopilot
autopilot off             # Disable autopilot
autopilot status          # Show state, next production date
autopilot force           # Force production now (skip cadence)
autopilot config          # Show weights and thresholds
autopilot learnings       # Show LEARNINGS.md summary
autopilot patterns thumb  # Show thumbnail patterns
autopilot ctr [title]     # Force CTR check for video
```

## Rules

- Code pushed to `main` auto-deploys via the hourly `git pull --ff-only`. Don't push broken code to main.
- The Slack bot (`pipeline_control.py`) runs as a background process. PID tracked at `/tmp/pipeline-bot.pid`.
- Healthcheck auto-restarts the bot and sends Slack alert. Don't assume the bot is always running.
- All logs go to `/tmp/pipeline-*.log` on VPS. Reference these when debugging production issues.
