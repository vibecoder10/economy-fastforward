"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: "#05080D",
          color: "#F0F2F8",
          fontFamily: "system-ui, -apple-system, sans-serif",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
          textAlign: "center",
          padding: 32,
        }}
      >
        <div>
          <h2 style={{ fontSize: 24, marginBottom: 12 }}>Something went wrong</h2>
          <p style={{ fontSize: 14, color: "#7A8199", marginBottom: 24 }}>
            A critical error occurred. Please try refreshing the page.
          </p>
          <button
            onClick={reset}
            style={{
              padding: "10px 24px",
              borderRadius: 10,
              background: "#00D4AA",
              color: "#05080D",
              border: "none",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try Again
          </button>
        </div>
      </body>
    </html>
  );
}
