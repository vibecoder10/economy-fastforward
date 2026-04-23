# Environment Variables Reference

See `.env.example` for all required variables. Critical ones:

| Variable | Service | Notes |
|----------|---------|-------|
| `ANTHROPIC_API_KEY` | Claude AI | Scripts, prompts, analysis |
| `AIRTABLE_API_KEY` | Airtable | Personal access token |
| `AIRTABLE_BASE_ID` | Airtable | `appCIcC58YSTwK3CE` |
| `ELEVENLABS_API_KEY` | ElevenLabs | Voice synthesis |
| `ELEVENLABS_VOICE_ID` | ElevenLabs | `G17SuINrv2H9FC6nvetn` |
| `OPENAI_API_KEY` | Whisper API | Audio transcription |
| `KIE_AI_API_KEY` | Kie.ai | Images, video, thumbnails |
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Google | Drive & Docs OAuth |
| `GOOGLE_DRIVE_FOLDER_ID` | Google Drive | Parent folder for all projects |
| `SLACK_BOT_TOKEN` | Slack | Bot control interface |
| `SLACK_CHANNEL_ID` | Slack | `C0A9U1X8NSW` |
| `REDIS_URL` | Redis / arq queue | `redis://localhost:6379` (default). Used by StoryEngine backend and arq worker. If Redis is unreachable, pipeline stages fall back to in-process BackgroundTasks (no error — check logs for "Redis/arq pool not available" warning). |
| `PER_USER_KEYS_ENABLED` | StoryEngine vault | Feature flag. Default `false`. When `true`, `vault.get_secret()` resolves user-scoped key first (`tenant:user:name`), then falls back to tenant-shared key (`tenant:name`). Raises `KeyError` if neither exists. Enable for PRD slice 4+ (per-user API key UI). |

## Rules

- Never commit `.env`. It's gitignored.
- When adding new env vars, ALWAYS update `.env.example` with a description.
- The Whisper dependency was removed from requirements.txt (saved 2GB on VPS). We use the API, not local Whisper.
