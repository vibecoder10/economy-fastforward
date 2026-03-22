import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Providers } from "./providers";
import { BottomTabs } from "@/components/nav/bottom-tabs";
import { Sidebar } from "@/components/nav/sidebar";
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
  themeColor: "#121212",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <link rel="apple-touch-icon" href="/icon-192.png" />
      </head>
      <body className="bg-[var(--background)] text-[var(--text-primary)] antialiased">
        <Providers>
          <div className="flex min-h-screen">
            {/* Desktop sidebar */}
            <Sidebar />

            {/* Main content */}
            <main className="flex-1 pb-16 md:pb-0 md:ml-60">
              <div className="mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6">{children}</div>
            </main>

            {/* Mobile bottom tabs */}
            <BottomTabs />
          </div>
        </Providers>
      </body>
    </html>
  );
}
