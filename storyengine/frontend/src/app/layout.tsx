import type { Metadata, Viewport } from "next";
import { Providers } from "./providers";
import { BottomTabs } from "@/components/nav/bottom-tabs";
import { Sidebar } from "@/components/nav/sidebar";
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
        <link rel="apple-touch-icon" href="/icon-192.png" />
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
          <div className="flex min-h-screen relative z-10">
            <Sidebar />
            <main className="flex-1 pb-16 md:pb-0 md:ml-60">
              <div className="mx-auto max-w-[1400px] px-6 py-6 md:px-12 md:py-10">
                {children}
              </div>
            </main>
            <BottomTabs />
          </div>
        </Providers>
      </body>
    </html>
  );
}
