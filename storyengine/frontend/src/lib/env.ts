// Single source of truth for public URL env vars.
//
// Next.js inlines NEXT_PUBLIC_* into the client bundle ONLY for literal
// property access (`process.env.NEXT_PUBLIC_X`). Dynamic access via
// `process.env[name]` inside a helper does NOT get inlined, which means the
// value is present at SSR time but `undefined` in the browser — the production
// guard below then throws on hydration and every page crashes into
// global-error.tsx. So every env read must be a literal access at module scope.

const API_URL_ENV = process.env.NEXT_PUBLIC_API_URL;
const RUBRIC_URL_ENV = process.env.NEXT_PUBLIC_RUBRIC_URL;
const CUSTOM_FILM_SCENE_CONTROL_ENV =
  process.env.NEXT_PUBLIC_CUSTOM_FILM_SCENE_CONTROL_V1;

function requireInProd(val: string | undefined, name: string, devFallback: string): string {
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

function optionalInProd(val: string | undefined, devFallback: string): string {
  if (val && val.length > 0) return val;
  if (process.env.NODE_ENV === "production") return "";
  return devFallback;
}

export const API_URL = requireInProd(API_URL_ENV, "NEXT_PUBLIC_API_URL", "http://localhost:8001");
// RUBRIC is the dev-only command-center on Osiris's Mac. Prod has no
// RUBRIC endpoint, so missing in prod is expected and non-fatal.
export const RUBRIC_URL = optionalInProd(RUBRIC_URL_ENV, "http://localhost:5050");
// Dark by default. This only exposes the frontend control surface; the backend
// independently enforces CUSTOM_FILM_SCENE_CONTROL_V1.
export const isSceneControlFrontendEnabled = (
  value: string | undefined,
): boolean => value === "true";
export const CUSTOM_FILM_SCENE_CONTROL_ENABLED =
  isSceneControlFrontendEnabled(CUSTOM_FILM_SCENE_CONTROL_ENV);
