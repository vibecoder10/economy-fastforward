# Manual Steps Required

These steps must be performed by a human with SSH access to the VPS.

## Update Crontab for Git Auto-Pull

The pipeline cron job should pull the latest code before each run to ensure it always uses the most recent version.

### Steps

1. SSH into the VPS
2. Run `crontab -e`
3. Find the existing pipeline cron line and replace it with:

```
0 * * * * cd /home/clawd/projects/economy-fastforward && git pull origin main --ff-only >> /tmp/pipeline.log 2>&1 && cd skills/video-pipeline && python3 pipeline.py --run-queue >> /tmp/pipeline.log 2>&1
```

4. Save and exit

### What changed

- Added `git pull origin main --ff-only` before the pipeline run
- The `--ff-only` flag ensures the pull only succeeds if it's a fast-forward merge (no conflicts). If the local branch has diverged, the pull will fail safely instead of creating a merge commit or corrupting the working tree
- Both commands log to `/tmp/pipeline.log`

### Verify

```bash
crontab -l
```

You should see the updated line with `git pull origin main --ff-only` before the pipeline command.
