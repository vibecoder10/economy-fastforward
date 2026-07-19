# Environment Variables Reference

See `.env.example` for all required variables. Critical ones:

| Variable | Service | Notes |
|----------|---------|-------|
| `ANTHROPIC_API_KEY` | Claude AI | Scripts, prompts, analysis |
| `AIRTABLE_API_KEY` | Airtable | Personal access token |
| `AIRTABLE_BASE_ID` | Airtable | `appCIcC58YSTwK3CE` |
| `ELEVENLABS_API_KEY` | ElevenLabs | Voice synthesis |
| `ELEVENLABS_VOICE_ID` | ElevenLabs | Ryan's own cloned voice, for HIS legacy cron pipeline only (this repo-root `.env`, separate process from the StoryEngine SaaS backend). Code default (no env set) is the tenant-neutral ElevenLabs stock voice `21m00Tcm4TlvDq8ikWAM` ("Rachel") — C34b/S10-2, see `pipeline_constants.py` `Models.VOICE_ID`. SaaS tenants configure their own via Settings → API Keys (vault `elevenlabs_voice_id`), never this env var. |
| `OPENAI_API_KEY` | Whisper API | Audio transcription |
| `KIE_AI_API_KEY` | Kie.ai | Images, video, thumbnails |
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Google | Drive & Docs OAuth |
| `GOOGLE_DRIVE_FOLDER_ID` | Google Drive | Parent folder for all projects |
| `SLACK_BOT_TOKEN` | Slack | Legacy cron pipeline only — bot control interface. The prototype channel is retired (tasks/decisions.md 2026-07-19); the StoryEngine SaaS backend's env must never set this. |
| `SLACK_CHANNEL_ID` | Slack | `C0A9U1X8NSW` (legacy cron pipeline only) |
| `SLACK_NOTIFICATIONS_ENABLED` | Slack | C34b/S10-3. Default `false` — `SlackClient` sends nothing even if `SLACK_BOT_TOKEN` is set, since it's reachable from SaaS-tenant runs via shared legacy bot code with no per-tenant Slack scoping. Set `true` only in the legacy cron pipeline's own `.env` if Ryan wants that channel's notifications back. |
| `REDIS_URL` | Redis / arq queue | `redis://localhost:6379` (default). Used by StoryEngine backend and arq worker. If Redis is unreachable, pipeline stages fall back to in-process BackgroundTasks (no error — check logs for "Redis/arq pool not available" warning). |
| `PER_USER_KEYS_ENABLED` | StoryEngine vault | Feature flag. Default `false`. When `true`, `vault.get_secret()` resolves user-scoped key first (`tenant:user:name`), then falls back to tenant-shared key (`tenant:name`). Raises `KeyError` if neither exists. Enable for PRD slice 4+ (per-user API key UI). |
| `YTDLP_COOKIES_FILE` | yt-dlp (StoryEngine backend) | Path to Netscape-format `cookies.txt` exported from a browser logged into YouTube. Fixes the "Sign in to confirm you're not a bot" block on the VPS IP that kills transcripts/metadata in `routes/niche.py` (Model A Video, competitor scraping, voice-learn). Optional — when unset, `~/.config/storyengine/youtube_cookies.txt` is used automatically if it exists (zero-config: drop the file, no restart needed). |
| `YTDLP_PROXY` | yt-dlp (StoryEngine backend) | Proxy URL (`http://` or `socks5://`) with an unflagged egress IP. Alternative to `YTDLP_COOKIES_FILE` for the same bot-check block. |

## Rules

- Never commit `.env`. It's gitignored.
- When adding new env vars, ALWAYS update `.env.example` with a description.
- The Whisper dependency was removed from requirements.txt (saved 2GB on VPS). We use the API, not local Whisper.
