# Manual VPS Steps

## Update Crontab for Auto-Pull

SSH into VPS and run `crontab -e`. Replace the existing pipeline line with:

```
0 * * * * cd /home/clawd/projects/economy-fastforward && git pull origin main --ff-only >> /tmp/pipeline.log 2>&1 && cd skills/video-pipeline && python3 pipeline.py --run-queue >> /tmp/pipeline.log 2>&1
```

The `--ff-only` flag ensures: only pull if clean fast-forward (no conflicts). If something is wrong, it skips the pull and runs existing code.

Verify with `crontab -l`.

## Test Git Pull Works

```bash
cd /home/clawd/projects/economy-fastforward && git pull origin main --ff-only
```

Should say "Already up to date." or pull new commits.
