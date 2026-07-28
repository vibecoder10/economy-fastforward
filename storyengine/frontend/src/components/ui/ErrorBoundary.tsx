"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Plain-English name of the panel this wraps, e.g. "chat", "canvas",
   * "media rail" — used in the fallback's message ("The chat hit a snag").
   * Keep it lowercase, no trailing punctuation. */
  label: string;
  /** When any value in this list changes (e.g. the open video's id), a
   * fallback that's currently showing clears itself and re-tries the real
   * children — so switching to a different, working video doesn't stay
   * stuck showing yesterday's crash. Compared by reference/`===`, same as a
   * React dependency array. */
  resetKeys?: ReadonlyArray<unknown>;
}

interface State {
  error: Error | null;
}

/**
 * Local crash net for one Director panel (bug-2 fix, 2026-07-27 audit).
 *
 * Before this, `layout.tsx` / `DirectorSurface.tsx` / `CanvasStage.tsx` had
 * NO error boundary anywhere in the chain, and `SceneAltitudeView` alone
 * fires four `useQuery` calls plus a video-actions query on every mount,
 * with `CanvasStage` fully unmounting/remounting it on every altitude
 * switch — one uncaught exception in any of those took out the WHOLE
 * Director surface (chat + canvas + rail, all of it) with nothing local to
 * catch it. A user would see a blank white screen and have no way to tell
 * whether the app died or just one panel did.
 *
 * This wraps one panel at a time (chat column, canvas, media rail, the
 * header — see DirectorSurface.tsx) so a crash in one never takes the
 * others down with it, and gives an honest, specific fallback: what broke,
 * in plain English, plus a retry — never a blank screen, never a raw stack
 * trace. Must be a class component; React only supports catching render
 * errors via `getDerivedStateFromError`/`componentDidCatch`, neither of
 * which has a hooks equivalent yet.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error(`[Director] "${this.props.label}" panel crashed:`, error, info.componentStack);
  }

  componentDidUpdate(prevProps: Props) {
    if (!this.state.error) return;
    const prev = prevProps.resetKeys ?? [];
    const next = this.props.resetKeys ?? [];
    const changed = prev.length !== next.length || prev.some((k, i) => k !== next[i]);
    if (changed) this.setState({ error: null });
  }

  private retry = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full min-h-[220px] w-full flex-col items-center justify-center gap-3 px-6 py-10 text-center">
          <div className="rounded-full p-3" style={{ background: "var(--red-dim)" }}>
            <AlertTriangle size={24} style={{ color: "var(--red)" }} />
          </div>
          <h3 className="text-[14.5px] font-semibold text-ink">The {this.props.label} hit a snag</h3>
          <p className="max-w-[340px] text-[12.5px] leading-relaxed text-dim">
            Something broke while rendering this part of the screen. The rest of the app is fine — tap retry, or
            reload the page if it keeps happening.
          </p>
          <button
            type="button"
            onClick={this.retry}
            className="inline-flex items-center gap-1.5 rounded-[9px] border border-line-soft bg-raise px-3.5 py-1.5 text-[12.5px] font-medium text-ink transition-colors hover:bg-white/[0.06]"
          >
            <RotateCcw size={13} /> Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
