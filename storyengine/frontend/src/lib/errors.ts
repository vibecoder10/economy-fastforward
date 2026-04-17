/**
 * humanizeError — convert raw fetch/API errors into copy a user can actually read.
 *
 * Raw errors users should NEVER see: "Failed to fetch", "NetworkError when
 * attempting to fetch resource", "API error 500: <body>", stack traces, etc.
 *
 * Strategy: inspect the error shape, return friendly copy. If we hit an
 * unrecognized shape, fall back to a neutral message + log the raw error
 * to the console so devs can still diagnose.
 */
export function humanizeError(
  err: unknown,
  fallback = "Something went wrong. Please try again."
): string {
  const raw =
    err instanceof Error
      ? err.message
      : typeof err === "string"
        ? err
        : "";

  // Network / offline / CORS blocked
  if (
    raw === "Failed to fetch" ||
    raw.startsWith("NetworkError") ||
    raw.startsWith("TypeError: Failed to fetch") ||
    raw.includes("ERR_CONNECTION_REFUSED") ||
    raw.includes("NetworkError when")
  ) {
    return "We couldn't reach our servers. Check your connection and try again.";
  }

  // Backend 5xx
  if (/^API error 5\d\d/.test(raw)) {
    return "Our servers hit a snag. Give it a moment and try again.";
  }

  // Backend 4xx auth
  if (/^API error 401/.test(raw) || raw === "Session expired — redirecting to login") {
    return "Your session expired. Please sign in again.";
  }

  // Backend 4xx plan / billing
  if (/^API error 402/.test(raw) || raw === "Plan limit reached") {
    return "You've hit a limit on your current plan.";
  }

  // Backend 4xx rate limit
  if (/^API error 429/.test(raw)) {
    return "You're doing that a lot. Give it a few seconds and try again.";
  }

  // Backend validation: if the API wrapper extracted a "detail" string from
  // the JSON body, it won't start with "API error"; it'll be human-ish
  // already (e.g. "Channel name too long"). Pass through when it looks safe.
  if (raw && !raw.startsWith("API error ") && raw.length < 160) {
    return raw;
  }

  // Last-resort fallback — log the raw error so devs can still find it
  if (typeof console !== "undefined" && raw) {
    console.warn("[humanizeError] unmapped:", raw);
  }
  return fallback;
}
