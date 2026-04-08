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
          Last updated: April 2026
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
              <li><strong>YouTube data:</strong> Channel analytics data you authorize us to access via YouTube Data API.</li>
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
              3. API Key Security
            </h2>
            <p>
              Your API keys are encrypted at rest and in transit. We never share your keys with other users or third parties beyond the services they are intended for. Keys are only used to execute pipeline operations you initiate. You can delete your keys at any time from the Settings page.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              4. Data Storage &amp; Retention
            </h2>
            <p>
              Your data is stored in Supabase PostgreSQL with row-level security. Each tenant&apos;s data is isolated. Generated assets (images, videos, audio) are stored in Google Drive under your account. We retain your data for as long as your account is active. Upon account deletion, all associated data is permanently removed within 30 days.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              5. Third-Party Services
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
              6. Cookies &amp; Tracking
            </h2>
            <p>
              We use essential cookies for authentication (session tokens). We do not use third-party tracking cookies or advertising trackers. We may use anonymous analytics to understand usage patterns.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              7. Your Rights
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
              8. Children&apos;s Privacy
            </h2>
            <p>
              StoryEngine is not intended for users under 18 years of age. We do not knowingly collect personal information from children.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              9. Changes to This Policy
            </h2>
            <p>
              We may update this privacy policy from time to time. We will notify you of material changes via email or in-app notification. Continued use of the Service after changes constitutes acceptance.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              10. Contact
            </h2>
            <p>
              For privacy-related questions or data requests, contact us at privacy@storyengine.ai.
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
