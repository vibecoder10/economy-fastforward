import type { Metadata, Viewport } from "next";
import { Providers } from "./providers";
import { AuthenticatedShell } from "@/components/auth/AuthenticatedShell";
import { AmbientBackground } from "@/components/layout/AmbientBackground";
import "./globals.css";

export const metadata: Metadata = {
  title: "StoryEngine",
  description: "Video production pipeline dashboard",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "StoryEngine",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  themeColor: "#05080D",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/icon-192.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/icon-192.svg" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Outfit:wght@300;400;500;600;700&family=Playfair+Display:wght@700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="font-body antialiased bg-[var(--bg-void)] text-[var(--text-primary)]">
        <Providers>
          <AmbientBackground />
          <AuthenticatedShell>{children}</AuthenticatedShell>
        </Providers>
      </body>
    </html>
  );
}
