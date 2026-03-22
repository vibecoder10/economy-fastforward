import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PredictMarkets",
  description:
    "Autonomous prediction market trading with Kalshi integration and AI-powered betting brain.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "PredictMarkets",
  },
};

export const viewport: Viewport = {
  themeColor: "#D4A853",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/icon.svg" />
      </head>
      <body className="font-body antialiased bg-background text-text-primary min-h-screen">
        {children}
      </body>
    </html>
  );
}
