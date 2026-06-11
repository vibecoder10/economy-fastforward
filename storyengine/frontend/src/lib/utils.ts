import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCost(cost: number): string {
  return `$${cost.toFixed(2)}`;
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}


/**
 * Google Drive `uc?export=download` links don't render in <img> tags (redirect
 * interstitials, no CORS, hard rate limits) — every asset stored on Drive was
 * showing as a broken image. Drive's image CDN serves the same public files
 * reliably: https://lh3.googleusercontent.com/d/<id>=w<width>.
 * Non-Drive URLs pass through untouched.
 */
export function toDisplayImageUrl(url?: string | null, width = 1920): string | undefined {
  if (!url) return undefined;
  if (!/^https?:\/\/drive\.google\.com\//.test(url)) return url;
  const m = url.match(/[?&]id=([\w-]+)/);
  if (!m) return url;
  return `https://lh3.googleusercontent.com/d/${m[1]}=w${width}`;
}
