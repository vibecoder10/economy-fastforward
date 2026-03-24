import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Removed "output: export" to support dynamic routes like /pipeline/[videoId]/storyboards
  // For production deployment, use a Node.js server or edge runtime
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
