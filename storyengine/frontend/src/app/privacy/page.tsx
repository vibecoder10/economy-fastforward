"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function PrivacyPage() {
  return (
    <div className="min-h-screen" style={{ background: "var(--bg-void)" }}>
      <div className="mx-auto max-w-3xl px-6 py-12">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm mb-8 transition-opacity hover:opacity-80"
          style={{ color: "var(--turquoise)" }}
        >
          <ArrowLeft size={14} />
          Back to StoryEngine
        </Link>

        <h1 className="text-4xl font-display mb-2" style={{ color: "var(--text-primary)" }}>
          Privacy Policy
        </h1>
        <p className="text-sm mb-8" style={{ color: "var(--text-tertiary)" }}>
          Last updated: September 2026
        </p>

        <div className="space-y-8 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              1. Information We Collect
            </h2>
            <p className="mb-2">We collect the following information when you use StoryEngine:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Account information:</strong> Name, email address, and Google profile data when you sign in with Google.</li>
              <li><strong>API keys:</strong> Third-party API keys you provide (stored encrypted in our secure vault).</li>
              <li><strong>Content data:</strong> Video titles, scripts, prompts, and generated assets created through the pipeline.</li>
              <li><strong>Usage data:</strong> Pipeline usage, feature interactions, and performance metrics.</li>
              <li><strong>YouTube data:</strong> When you connect a YouTube channel, the channel ID and name, your channel&apos;s video list and public video statistics (views, likes, comments), and the analytics you authorize, read through YouTube API Services. See section 3.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              2. How We Use Your Information
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>To provide and operate the video production pipeline.</li>
              <li>To authenticate your identity and manage your account.</li>
              <li>To execute API calls to third-party services using your provided keys.</li>
              <li>To display analytics and performance data for your videos.</li>
              <li>To improve the Service based on aggregate usage patterns.</li>
              <li>To send important account notifications (billing, security, service updates).</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              3. Google &amp; YouTube Data
            </h2>
            <p className="mb-2">
              StoryEngine uses YouTube API Services. By connecting a YouTube channel you agree to the <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer" className="underline" style={{ color: "var(--turquoise)" }}>YouTube Terms of Service</a>, and Google&apos;s handling of your data is covered by the <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" className="underline" style={{ color: "var(--turquoise)" }}>Google Privacy Policy</a>.
            </p>
            <p className="mb-2">When you connect Google, StoryEngine asks for these permissions and uses them only for these features:</p>
            <ul className="list-disc pl-5 space-y-1 mb-2">
              <li><strong>Upload videos to YouTube (youtube.upload):</strong> to upload the videos you produce in StoryEngine to your channel. Uploads are unlisted unless you choose another setting, and use the title, description, tags and thumbnail you approve. StoryEngine never makes a video public on its own.</li>
              <li><strong>View your YouTube account (youtube.readonly):</strong> to confirm which channel is connected, check that each upload landed on that channel, and read your videos and their statistics to show performance and suggest titles and topics.</li>
              <li><strong>Google Drive files created by StoryEngine (drive.file):</strong> to save the scripts, images, audio and videos StoryEngine makes for you. StoryEngine cannot see any other files in your Drive.</li>
            </ul>
            <p className="mb-2">
              <strong>How it is stored:</strong> the Google access key (refresh token) is stored in our database, which is encrypted at rest, and is used only by our servers. Channel details and video statistics are stored with your workspace, isolated from other workspaces.
            </p>
            <p className="mb-2">
              <strong>How it is shared:</strong> we do not sell Google user data, use it for advertising, or give it to data brokers. To produce your features (for example, suggesting titles based on how your past videos performed), video statistics may be sent to the AI providers listed in section 6, only to produce results for you. Google user data is never used to train general AI or machine-learning models.
            </p>
            <p className="mb-2">
              StoryEngine&apos;s use and transfer of information received from Google APIs adheres to the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer" className="underline" style={{ color: "var(--turquoise)" }}>Google API Services User Data Policy</a>, including the Limited Use requirements.
            </p>
            <p>
              <strong>How to remove access:</strong> disconnect YouTube or Google Drive on the StoryEngine Settings page, which deletes the stored access key at once, or remove StoryEngine at <a href="https://myaccount.google.com/connections" target="_blank" rel="noopener noreferrer" className="underline" style={{ color: "var(--turquoise)" }}>Google security settings</a>. To delete the YouTube data we stored, delete your account or email us (section 11); we delete it within 30 days.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              4. API Key Security
            </h2>
            <p>
              Your API keys are encrypted at rest and in transit. We never share your keys with other users or third parties beyond the services they are intended for. Keys are only used to execute pipeline operations you initiate. You can delete your keys at any time from the Settings page.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              5. Data Storage &amp; Retention
            </h2>
            <p>
              Your data is stored in Supabase PostgreSQL with row-level security. Each tenant&apos;s data is isolated. Generated assets (images, videos, audio) are stored in Google Drive under your account. We retain your data for as long as your account is active. Upon account deletion, all associated data is permanently removed within 30 days.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              6. Third-Party Services
            </h2>
            <p className="mb-2">StoryEngine integrates with the following third-party services, each with their own privacy policies:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Google (Authentication, YouTube Data API, Google Drive)</li>
              <li>Stripe (Payment processing)</li>
              <li>Anthropic (AI script generation)</li>
              <li>ElevenLabs (Voice synthesis)</li>
              <li>OpenAI (Audio transcription)</li>
            </ul>
            <p className="mt-2">
              We recommend reviewing each provider&apos;s privacy policy. We are not responsible for the data practices of these third-party services.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              7. Cookies &amp; Tracking
            </h2>
            <p>
              We use essential cookies for authentication (session tokens). We do not use third-party tracking cookies or advertising trackers. We may use anonymous analytics to understand usage patterns.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              8. Your Rights
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Access:</strong> You can view all your data through the StoryEngine dashboard.</li>
              <li><strong>Deletion:</strong> You can delete your account and all associated data at any time.</li>
              <li><strong>Export:</strong> You can export your video data, scripts, and assets.</li>
              <li><strong>Correction:</strong> You can update your profile and settings at any time.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              9. Children&apos;s Privacy
            </h2>
            <p>
              StoryEngine is not intended for users under 18 years of age. We do not knowingly collect personal information from children.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              10. Changes to This Policy
            </h2>
            <p>
              We may update this privacy policy from time to time. We will notify you of material changes via email or in-app notification. Continued use of the Service after changes constitutes acceptance.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              11. Contact
            </h2>
            <p>
              For privacy-related questions or data requests, contact us at ryan@nativestates.ai.
            </p>
          </section>
        </div>

        <div className="mt-12 pt-6" style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <div className="flex gap-4 text-xs" style={{ color: "var(--text-tertiary)" }}>
            <Link href="/terms" className="hover:underline">Terms of Service</Link>
            <span>&middot;</span>
            <Link href="/" className="hover:underline">Home</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
