import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0A0A0B",
        surface: "#141415",
        "surface-hover": "#1C1C1E",
        border: "#2A2A2D",
        "border-hover": "#3A3A3D",
        "text-primary": "#F5F5F7",
        "text-secondary": "#8E8E93",
        "text-tertiary": "#636366",
        accent: "#D4A853",
        "accent-hover": "#E0B965",
        "accent-dim": "#A88A3D",
        error: "#FF453A",
        success: "#30D158",
        warning: "#FFD60A",
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        body: ["var(--font-body)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
