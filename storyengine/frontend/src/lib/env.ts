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

function resolveRequired(name: string, devFallback: string): string {
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

// Optional: missing-in-prod returns empty string. Callers MUST gate on
// truthiness before using (e.g. `if (!RUBRIC_URL) return;`). Reserved for
// dev-only telemetry — never for paths the user depends on.
function resolveOptional(name: string, devFallback: string): string {
  const val = process.env[name];
  if (val && val.length > 0) return val;
  if (process.env.NODE_ENV === "production") return "";
  return devFallback;
}

export const API_URL = resolveRequired("NEXT_PUBLIC_API_URL", "http://localhost:8001");
// RUBRIC is the dev-only command-center on Osiris's Mac. Prod has no
// RUBRIC endpoint, so missing in prod is expected and non-fatal.
export const RUBRIC_URL = resolveOptional(
  "NEXT_PUBLIC_RUBRIC_URL",
  "http://localhost:5050",
);
