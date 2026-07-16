"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export interface ConfirmOptions {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}

// In-app replacement for window.confirm. The native dialog blocks the renderer
// thread synchronously, which wedges browser automation - this dialog keeps the
// same ask-then-proceed contract without freezing the page.
//
// Deliberately NOT built on ui/modal.tsx: its AnimatePresence exit never
// unmounted the closed dialog, leaving an invisible full-screen backdrop that
// blocked every click (verified in dev 2026-07-15; Modal fixed 2026-07-16 with
// keyed direct children). Plain conditional rendering matches the
// revision-modal idiom in ScriptVoiceTab and cannot wedge; moving this back
// onto Modal is now possible but optional.
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolverRef = useRef<((confirmed: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((next) => (
    new Promise<boolean>((resolve) => {
      // A second request while one is open cancels the first, like a dismissed
      // native dialog would.
      resolverRef.current?.(false);
      resolverRef.current = resolve;
      setOptions(next);
    })
  ), []);

  const settle = useCallback((confirmed: boolean) => {
    resolverRef.current?.(confirmed);
    resolverRef.current = null;
    setOptions(null);
  }, []);

  useEffect(() => {
    if (!options) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") settle(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [options, settle]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {options && (
        <div
          data-testid="confirm-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => settle(false)}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            className="w-full max-w-md rounded-xl p-6 space-y-4"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            {options.title && (
              <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>
                {options.title}
              </h3>
            )}
            <p
              data-testid="confirm-modal-message"
              className="text-sm leading-relaxed whitespace-pre-line"
              style={{ color: "var(--text-primary)" }}
            >
              {options.message}
            </p>
            <div className="flex gap-2 justify-end">
              <button
                data-testid="confirm-modal-cancel"
                onClick={() => settle(false)}
                className="px-4 py-2 rounded-lg text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                {options.cancelLabel || "Cancel"}
              </button>
              <button
                data-testid="confirm-modal-confirm"
                autoFocus
                onClick={() => settle(true)}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                {options.confirmLabel || "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
