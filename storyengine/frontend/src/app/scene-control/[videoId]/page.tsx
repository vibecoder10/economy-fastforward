"use client";

import {useMemo, useState} from "react";
import Link from "next/link";
import {useParams} from "next/navigation";
import {useQuery} from "@tanstack/react-query";
import {ArrowLeft, Loader2, Plus, RefreshCw} from "lucide-react";
import {
  SceneControlCockpit,
  adaptSceneControlSnapshot,
  type SceneControlQuoteRequest,
  type SceneControlRejectRequest,
  type SceneControlTransitionRequest,
} from "@/components/custom-film";
import {ApiError} from "@/lib/api";
import {
  createSceneControlScene,
  getSceneControl,
  putSceneControlFilmLock,
  quoteSceneControlOperation,
  reviseSceneControlScene,
  transitionSceneControlScene,
  type SceneControlApiQuote,
  type SceneControlApiSceneContract,
  type SceneControlApiState,
  type SceneControlChangedGate,
  type SceneControlLockKind,
} from "@/lib/scene-control-api";

const REJECT_GATE: Partial<
  Record<SceneControlApiState, SceneControlChangedGate>
> = {
  plan_approved: "plan",
  storyboard_approved: "storyboard",
  imagery_approved: "imagery",
  animation_approved: "animation",
  audio_approved: "audio",
  assembled: "assembly",
};

const emptyContract = `{
  "scene_number": 1,
  "purpose": "",
  "target_duration_frames": 0,
  "story_time": "",
  "opening_state": "",
  "state_change": "",
  "character_ids": [],
  "environment_id": "",
  "active_prop_ids": [],
  "continuity_in": "",
  "continuity_out": "",
  "dialogue_turns": [],
  "silent_action_beats": [],
  "shot_ids": []
}`;

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Scene Control request failed";
}

export default function SceneControlPage() {
  const params = useParams<{videoId: string}>();
  const videoId = params.videoId;
  const [quote, setQuote] = useState<SceneControlApiQuote>();
  const [notice, setNotice] = useState<string>();
  const [failure, setFailure] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [contractText, setContractText] = useState(emptyContract);

  const query = useQuery({
    queryKey: ["scene-control", videoId],
    queryFn: () => getSceneControl(videoId),
    enabled: Boolean(videoId),
    retry: false,
  });

  const adapted = useMemo(
    () => {
      if (!query.data) return {snapshot: null, error: undefined};
      try {
        return {
          snapshot: adaptSceneControlSnapshot(query.data, quote),
          error: undefined,
        };
      } catch (error) {
        return {snapshot: null, error: messageFrom(error)};
      }
    },
    [query.data, quote],
  );
  const cockpitSnapshot = adapted.snapshot;

  const refreshCanonical = async () => {
    setQuote(undefined);
    const result = await query.refetch();
    if (result.error) throw result.error;
  };

  const runCanonicalMutation = async (
    operation: () => Promise<unknown>,
    success: string,
  ) => {
    setBusy(true);
    setNotice(undefined);
    setFailure(undefined);
    try {
      await operation();
      await refreshCanonical();
      setNotice(success);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setQuote(undefined);
        await query.refetch();
        setFailure(
          "This scene changed in another session. Canonical state was refreshed; review it before trying again.",
        );
      } else {
        setFailure(messageFrom(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const reviewLock = (lockKind: string, payload: unknown) => {
    void runCanonicalMutation(
      () =>
        putSceneControlFilmLock(
          videoId,
          lockKind as SceneControlLockKind,
          payload,
        ),
      `${lockKind} lock saved and refreshed from canonical state.`,
    );
  };

  const transition = (request: SceneControlTransitionRequest) => {
    if (request.to_state === "draft") {
      setFailure("Draft is not a valid forward transition target.");
      return;
    }
    const targetState = request.to_state;
    void runCanonicalMutation(
      () =>
        transitionSceneControlScene(videoId, request.scene_id, {
          expected_revision_hash: request.expected_revision_hash,
          target_state: targetState,
          evidence_hash: request.evidence_hash,
        }),
      `Scene advanced to ${request.to_state.replaceAll("_", " ")}.`,
    );
  };

  const reject = (request: SceneControlRejectRequest) => {
    const scene = query.data?.scenes.find(
      ({scene_id}) => scene_id === request.scene_id,
    );
    const gate = scene ? REJECT_GATE[scene.state] : undefined;
    if (!gate) {
      setFailure("This scene state cannot be revised to a prior review gate.");
      return;
    }
    void runCanonicalMutation(
      () =>
        reviseSceneControlScene(videoId, request.scene_id, {
          expected_revision_hash: request.expected_revision_hash,
          changed_gate: gate,
        }),
      `Scene returned for ${gate} revision.`,
    );
  };

  const requestQuote = async (request: SceneControlQuoteRequest) => {
    setBusy(true);
    setNotice(undefined);
    setFailure(undefined);
    try {
      const nextQuote = await quoteSceneControlOperation(
        videoId,
        request.scene_id,
        {
          expected_revision_hash: request.expected_revision_hash,
          operation_type: request.operation_type,
          shot_id: request.shot_id,
        },
      );
      setQuote(nextQuote);
      setNotice("Exact quote loaded. No provider work was approved or started.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await refreshCanonical();
        setFailure(
          "This scene changed before the quote completed. Canonical state was refreshed.",
        );
      } else {
        setFailure(messageFrom(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const createScene = () => {
    let parsed: SceneControlApiSceneContract;
    try {
      parsed = JSON.parse(contractText) as SceneControlApiSceneContract;
    } catch {
      setFailure("Scene contract must be valid JSON.");
      return;
    }
    void runCanonicalMutation(
      () => createSceneControlScene(videoId, parsed),
      `Scene ${parsed.scene_number} draft created. No generation was started.`,
    );
  };

  return (
    <main className="mx-auto w-full max-w-[1600px] px-4 pb-24 pt-6 sm:px-6 lg:px-8">
      <Link
        href={`/pipeline/${encodeURIComponent(videoId)}`}
        className="mb-5 inline-flex items-center gap-2 text-xs font-semibold"
        style={{color: "var(--text-secondary)"}}
      >
        <ArrowLeft size={14} />
        Back to production
      </Link>

      {notice ? (
        <div className="mb-4 rounded-xl p-3 text-xs" role="status" style={{background: "var(--green-dim)", color: "var(--green)"}}>
          {notice}
        </div>
      ) : null}
      {failure ? (
        <div className="mb-4 rounded-xl p-3 text-xs" role="alert" style={{background: "var(--red-dim)", color: "var(--red)"}}>
          {failure}
        </div>
      ) : null}

      {query.isLoading ? (
        <div className="flex min-h-80 items-center justify-center gap-2 text-sm" style={{color: "var(--text-secondary)"}}>
          <Loader2 className="animate-spin" size={18} />
          Loading canonical Scene Control state…
        </div>
      ) : query.error ? (
        <section className="glass-card p-6">
          <h1 className="text-lg font-bold">Scene Control is unavailable</h1>
          <p className="mt-2 text-xs" style={{color: "var(--text-secondary)"}}>
            {messageFrom(query.error)}
          </p>
          <button type="button" onClick={() => void query.refetch()} className="mt-4 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold" style={{background: "var(--turquoise)", color: "var(--bg-void)"}}>
            <RefreshCw size={14} />
            Retry
          </button>
        </section>
      ) : (
        <>
          {adapted.error ? (
            <section className="glass-card p-5" role="alert">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{color: "var(--red)"}}>
                Scene Control read model rejected
              </p>
              <h1 className="mt-1 text-xl font-bold">Canonical shot detail is invalid</h1>
              <p className="mt-2 text-xs" style={{color: "var(--text-secondary)"}}>
                {adapted.error}. The cockpit is hidden so incomplete shot data cannot be mistaken for production truth.
              </p>
              <button type="button" onClick={() => void query.refetch()} className="mt-4 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold" style={{background: "var(--turquoise)", color: "var(--bg-void)"}}>
                <RefreshCw size={14} />
                Refetch canonical state
              </button>
            </section>
          ) : cockpitSnapshot ? (
            <SceneControlCockpit
              snapshot={cockpitSnapshot}
              busy={busy || query.isFetching}
              onReviewFilmLock={reviewLock}
              onTransition={transition}
              onReject={reject}
              onRequestQuote={(request) => void requestQuote(request)}
            />
          ) : (
            <section className="glass-card p-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{color: "var(--turquoise)"}}>
                Scene Control
              </p>
              <h1 className="mt-1 text-xl font-bold">No scene contract yet</h1>
              <p className="mt-2 text-xs" style={{color: "var(--text-secondary)"}}>
                Create the first deterministic draft from an exact scene contract. This action does not generate media.
              </p>
            </section>
          )}

          <details className="glass-card mt-4">
            <summary className="cursor-pointer list-none px-4 py-4 text-sm font-bold">
              Add exact scene contract
            </summary>
            <div className="border-t p-4" style={{borderColor: "var(--border-subtle)"}}>
              <label htmlFor="scene-contract" className="text-xs font-semibold">
                Scene contract JSON
              </label>
              <textarea
                id="scene-contract"
                value={contractText}
                onChange={(event) => setContractText(event.target.value)}
                spellCheck={false}
                rows={18}
                className="mt-2 w-full rounded-xl p-3 font-mono text-xs"
                style={{background: "var(--bg-deep)", border: "1px solid var(--border-subtle)"}}
              />
              <button
                type="button"
                disabled={busy}
                onClick={createScene}
                className="mt-3 inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold disabled:opacity-40"
                style={{background: "var(--turquoise)", color: "var(--bg-void)"}}
              >
                <Plus size={15} />
                Create draft scene — no generation
              </button>
            </div>
          </details>
        </>
      )}
    </main>
  );
}
