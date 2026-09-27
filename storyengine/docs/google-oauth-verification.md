# Google OAuth verification - StoryEngine

Why: the YouTube login expires every 7 days while the Google app is in "Testing"
(Google rule for external apps). Anton's DvsU login (saved 2026-09-12) died this way.
Publishing to "In production" stops the expiry at once; verification removes the
"unverified app" warning and the 100-user cap.

## Checklist (in order)

| # | Step | Who | Where |
|---|------|-----|-------|
| 1 | Publish app ("In production") | Ryan | Google Cloud Console -> Google Auth Platform -> Audience -> Publish app |
| 2 | Verify `storyengine.dev` | Ryan | Google Search Console -> Add property -> Domain -> DNS TXT record. Use the same Google account that owns the Cloud project |
| 3 | Branding: app name `StoryEngine`, logo (120x120 PNG), support email, homepage `https://storyengine.dev`, privacy `https://storyengine.dev/privacy`, terms `https://storyengine.dev/terms`, authorized domain `storyengine.dev`, developer contact email | Ryan | Google Auth Platform -> Branding |
| 4 | Scopes: add exactly the 3 below, nothing else | Ryan | Google Auth Platform -> Data Access |
| 5 | Record the demo video (script below), upload to YouTube as Unlisted | Ryan | - |
| 6 | Paste the justifications below + the video link, submit | Ryan | Google Auth Platform -> Verification Center |
| 7 | Answer Google's emails fast - reviewers stop the clock while they wait | Ryan | the developer contact inbox |

Sensitive scopes only (no restricted ones), so no paid security assessment.

## Scopes and justifications (paste as-is)

**https://www.googleapis.com/auth/youtube.upload**
StoryEngine is a video production tool for YouTube creators. The user writes and renders a
video inside StoryEngine, then clicks Upload. StoryEngine uploads that one finished video file
to the user's own connected channel as an unlisted draft, with the title, description, tags
and thumbnail the user approved. The user then reviews it in YouTube Studio and publishes it
themselves. StoryEngine never makes a video public on its own. No narrower scope can upload a
video; youtube.readonly cannot insert videos.

**https://www.googleapis.com/auth/youtube.readonly**
Used for three user-facing features: (1) after sign-in, show the user which channel is
connected (channel name and ID) so they can confirm it is the right one; (2) after each
upload, read the uploaded video back to confirm it landed on that same channel and finished
processing; (3) list the user's own videos and their view/like/comment counts on the
Analytics page, and use them to suggest titles and topics for the user's next video.
youtube.upload alone cannot read the channel or the video list. We request read-only
access, not the full youtube scope, because StoryEngine never edits or deletes existing videos.

**https://www.googleapis.com/auth/drive.file**
Saves the scripts, images, audio and rendered videos StoryEngine creates into the user's
Google Drive, so the user owns and can download every file. drive.file only allows access to
files StoryEngine itself created; StoryEngine cannot see any other file in the user's Drive.
(drive.file is non-sensitive; listed here for completeness.)

**Data handling (for the questionnaire)**
- Stored: refresh token and channel ID/name in our database (encrypted at rest); video
  statistics per workspace, isolated by tenant.
- Shared: never sold, never used for ads. Video statistics may be sent to our AI providers
  only to generate title/topic suggestions for that same user. Never used to train models.
- Removal: Settings -> Disconnect deletes the token at once; account deletion or an email
  request deletes stored YouTube data within 30 days.

## Demo video script (3-5 min, screen recording, English, no music needed)

Google rejects videos that do not show the consent screen with the Client ID. Record in a
browser where the address bar is visible the whole time.

1. **0:00** Open `https://storyengine.dev`. Show the homepage, scroll to the footer, click
   Privacy Policy, scroll to section 3 "Google & YouTube Data". Go back.
2. **0:40** Sign in. Open **Settings**. Click **Connect YouTube**.
3. **1:00** On Google's consent screen: **pause and zoom on the address bar** so the
   `client_id=...` value is readable. Show the app name "StoryEngine" and the permission list.
   Say (or caption): "StoryEngine asks to upload videos and view the YouTube account."
   Click **Allow**.
4. **1:30** Back in Settings: show the connected channel name. Caption: "youtube.readonly -
   shows which channel is connected."
5. **1:50** Open a finished (rendered) video (Pipeline -> the video). Open its **Upload** tab and start the upload. Show the unlisted setting.
   Wait for the success message. Caption: "youtube.upload - uploads this video as an unlisted
   draft to the user's own channel."
6. **2:40** Open YouTube Studio in a new tab. Show the new video there as **Unlisted**.
   Caption: "The user publishes it themselves."
7. **3:10** Back in StoryEngine, open **Analytics**. Show the channel's videos and view counts.
   Caption: "youtube.readonly - the user's own videos and statistics."
8. **3:40** Open the video's Drive folder link. Show the files StoryEngine created.
   Caption: "drive.file - only files StoryEngine made."
9. **4:00** Settings -> **Disconnect YouTube**. Caption: "Disconnect deletes the stored token."

Use a test channel you own for the recording, not a customer's channel.

## Known gaps (fix before or during review)

- **Contact email:** privacy, terms and pricing pages now use `ryan@nativestates.ai`. Use the same address as the support email on the consent screen.
- **YouTube data deletion:** Disconnect removes the token, but the stored video statistics
  (`channel_videos`) stay. YouTube API policy expects stored API data to be deleted (or
  refreshed) - the policy text now promises deletion within 30 days on request or account
  deletion; a scheduled cleanup does not exist yet.
- **Logo:** Branding needs a logo file; changing the logo later restarts brand review.
