import { API_URL } from "@/lib/env";
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
 * C25a: the media proxy now requires a tenant-scoped auth token — `<img>`/
 * `<video>` tags can't send an Authorization header, so it travels as a
 * `?token=` query param instead (the same query-param pattern this backend
 * already trusts for SSE — auth.verify_token's own docstring — and for audio
 * playback — routes/videos.py's audio-token). We reuse the SAME session
 * token the app already holds in localStorage for every fetchApi() call:
 * no separate token-fetch-and-cache dance, and it's the exact credential the
 * backend already treats as this user's full session everywhere else.
 * Never call this at module load / on the server — localStorage is
 * browser-only, hence the `typeof window` guard (SSR just gets the bare URL,
 * which the browser then re-requests via the client with `withMediaAuth`
 * applied — the proxy 401s on a bare URL, same as any other authed route).
 */
export function withMediaAuth(url: string): string {
  if (typeof window === "undefined") return url;
  const token = localStorage.getItem("token");
  if (!token) return url;
  return appendQueryParam(url, "token", token);
}

/**
 * Append a query param without producing a second `?` — every call site that
 * tacks something onto a `toDisplayImageUrl`/`toDisplayVideoUrl` result (e.g.
 * a `cb=` cache-buster) must go through this, now that those results already
 * carry a `?token=` (C25a). A hand-rolled `${url}?cb=${bust}` after that would
 * produce `...?token=xyz?cb=123` — an invalid second `?` that silently loses
 * the cache-buster instead of erroring, which is worse.
 */
export function appendQueryParam(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${key}=${encodeURIComponent(value)}`;
}

const MEDIA_PROXY_PATH_RE = /\/api\/media\/drive\//;

/**
 * Google Drive `uc?export=download` links don't render in <img> tags (redirect
 * interstitials, no CORS, hard rate limits) — every asset stored on Drive was
 * showing as a broken image. Drive's image CDN serves the same public files
 * reliably: https://lh3.googleusercontent.com/d/<id>=w<width>.
 * Non-Drive URLs pass through untouched (except an already-proxied URL —
 * e.g. one the backend built server-side, like chat's SceneBoardsGrid card —
 * which still needs auth attached even though no Drive->proxy conversion
 * is needed).
 */
export function toDisplayImageUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (MEDIA_PROXY_PATH_RE.test(url)) return withMediaAuth(url);
  if (!/^https?:\/\/drive\.google\.com\//.test(url)) return url;
  const m = url.match(/[?&]id=([\w-]+)/) || url.match(/\/d\/([\w-]+)/);
  if (!m) return url;
  // Backend media proxy streams via the authorized Drive API — public Drive
  // links (uc, lh3) randomly degrade into HTML interstitials.
  return withMediaAuth(`${API_URL}/api/media/drive/${m[1]}`);
}

/**
 * Final rendered video lives on Drive as a `uc?...&export=download` link, which
 * a browser <video> can't stream (it downloads / shows an interstitial). The
 * media proxy serves the bytes (video/mp4) with HTTP Range support, so route the
 * player through it. Non-Drive URLs pass through untouched (see
 * toDisplayImageUrl for the already-proxied-URL case).
 */
export function toDisplayVideoUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (MEDIA_PROXY_PATH_RE.test(url)) return withMediaAuth(url);
  if (!/^https?:\/\/drive\.google\.com\//.test(url)) return url;
  const m = url.match(/[?&]id=([\w-]+)/) || url.match(/\/d\/([\w-]+)/);
  if (!m) return url;
  return withMediaAuth(`${API_URL}/api/media/drive/${m[1]}`);
}
