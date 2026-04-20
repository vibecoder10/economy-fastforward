// Single source of truth for public URL env vars.
//
// Why this exists: Next.js bakes NEXT_PUBLIC_* into the client bundle at BUILD
// time. A missing env during `next build` used to silently fall back to
// `http://localhost:8001`, meaning a misconfigured prod deploy would ship
// broken artifacts that only revealed themselves at first user load. The guard
// below throws during module init so a prod build without a real API URL
// fails loudly at build time (or at worst, on the server's first render) —
// never silently.
//
// Dev keeps the localhost fallback so `next dev` works with no .env.

function resolve(name: string, devFallback: string): string {
  const val = process.env[name];
  if (val && val.length > 0) return val;
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      `${name} is required in production builds. ` +
        `Set it in .env.production or the deploy environment before running next build. ` +
        `Falling back to localhost in prod would silently break every API call.`,
    );
  }
  return devFallback;
}

export const API_URL = resolve("NEXT_PUBLIC_API_URL", "http://localhost:8001");
export const RUBRIC_URL = resolve(
  "NEXT_PUBLIC_RUBRIC_URL",
  "http://localhost:5050",
);
