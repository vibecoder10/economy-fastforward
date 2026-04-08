"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function TermsPage() {
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
          Terms of Service
        </h1>
        <p className="text-sm mb-8" style={{ color: "var(--text-tertiary)" }}>
          Last updated: April 2026
        </p>

        <div className="space-y-8 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              1. Acceptance of Terms
            </h2>
            <p>
              By accessing or using StoryEngine (&quot;the Service&quot;), you agree to be bound by these Terms of Service. If you do not agree to these terms, do not use the Service.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              2. Description of Service
            </h2>
            <p>
              StoryEngine is an AI-powered video production platform that automates the creation of YouTube videos. The Service includes research, scripting, voice synthesis, image generation, video rendering, and analytics tools.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              3. User Accounts
            </h2>
            <p>
              You must create an account to use the Service. You are responsible for maintaining the confidentiality of your account credentials and for all activities under your account. You must be at least 18 years old to use the Service.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              4. API Keys &amp; Third-Party Services
            </h2>
            <p>
              StoryEngine operates on a Bring Your Own Key (BYOK) model. You provide your own API keys for third-party services (Anthropic, ElevenLabs, Kie.ai, Google, OpenAI). You are responsible for any costs incurred through these services. We store your API keys securely and only use them to execute pipeline operations on your behalf.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              5. Content Ownership
            </h2>
            <p>
              You retain full ownership of all content produced through the Service, including scripts, images, videos, and thumbnails. StoryEngine does not claim any intellectual property rights over your generated content.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              6. Acceptable Use
            </h2>
            <p>
              You agree not to use the Service to create content that is illegal, defamatory, harassing, or that violates the rights of others. You are solely responsible for ensuring your content complies with YouTube&apos;s Terms of Service and Community Guidelines.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              7. Billing &amp; Subscriptions
            </h2>
            <p>
              Paid plans are billed monthly via Stripe. You may cancel at any time. Cancellation takes effect at the end of the current billing period. Refunds are provided at our discretion for unused portions of the current billing cycle.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              8. Service Availability
            </h2>
            <p>
              We strive to maintain high availability but do not guarantee uninterrupted service. We may perform maintenance, updates, or experience outages. We are not liable for any losses resulting from service interruptions.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              9. Limitation of Liability
            </h2>
            <p>
              StoryEngine is provided &quot;as is&quot; without warranties of any kind. We are not liable for any indirect, incidental, or consequential damages arising from your use of the Service. Our total liability shall not exceed the amount you paid in the 12 months preceding the claim.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              10. Changes to Terms
            </h2>
            <p>
              We may update these terms from time to time. Continued use of the Service after changes constitutes acceptance of the updated terms. We will notify you of material changes via email or in-app notification.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              11. Contact
            </h2>
            <p>
              For questions about these terms, contact us at support@storyengine.ai.
            </p>
          </section>
        </div>

        <div className="mt-12 pt-6" style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <div className="flex gap-4 text-xs" style={{ color: "var(--text-tertiary)" }}>
            <Link href="/privacy" className="hover:underline">Privacy Policy</Link>
            <span>&middot;</span>
            <Link href="/" className="hover:underline">Home</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
