import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PredictMarkets — Prediction Market Trading Platform",
  description:
    "Autonomous prediction market trading with Kalshi integration and AI-powered betting brain.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-body antialiased bg-background text-text-primary min-h-screen">
        {children}
      </body>
    </html>
  );
}
