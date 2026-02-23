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

## Rules

- Never commit `.env`. It's gitignored.
- When adding new env vars, ALWAYS update `.env.example` with a description.
- The Whisper dependency was removed from requirements.txt (saved 2GB on VPS). We use the API, not local Whisper.
