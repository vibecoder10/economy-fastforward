import type { NextConfig } from "next";

// Security headers. These apply to every response.
// NOTE: the CSP here is deliberately the *non-resource* subset (frame-ancestors,
// base-uri, object-src) — it can't break script/style/image/API loading. A full
// script-src/connect-src CSP needs the final HTTPS API origin (Ryan's reverse-
// proxy step) and real browser testing before it's safe to turn on; tracked in
// LAUNCH-READINESS Phase 6/8.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
  },
  // HSTS only takes effect over HTTPS; harmless until the cert is live.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  turbopack: {
    root: process.cwd(),
  },
  // Removed "output: export" to support dynamic routes like /pipeline/[videoId]/storyboards
  // For production deployment, use a Node.js server or edge runtime
  images: {
    unoptimized: true,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async redirects() {
    // The Competitors page was folded into Discovery (Competitor Modeling).
    return [{ source: "/competitors", destination: "/discovery", permanent: false }];
  },
};

export default nextConfig;
