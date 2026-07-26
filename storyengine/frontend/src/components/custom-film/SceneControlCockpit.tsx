"use client";

import {useEffect, useMemo, useState} from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleDollarSign,
  Clapperboard,
  Film,
  LockKeyhole,
  MessageSquareText,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Volume2,
} from "lucide-react";
import {GlassCard} from "@/components/ui/GlassCard";
import {
  currentScene,
  formatCents,
  nextSceneState,
  previousReviewState,
  sceneStateLabel,
  transitionLabel,
  validateSceneControlSnapshot,
} from "./scene-control-model";
import type {
  ArtifactStatus,
  SceneControlCockpitProps,
  SceneControlScene,
  SceneControlShot,
} from "./scene-control-types";

const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--turquoise)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-void)]";

const railColors = {
  current: {color: "var(--turquoise)", background: "var(--turquoise-bg)"},
  accepted: {color: "var(--green)", background: "var(--green-dim)"},
  locked: {color: "var(--text-tertiary)", background: "var(--bg-deep)"},
  invalidated: {color: "var(--red)", background: "var(--red-dim)"},
} as const;

const artifactColors: Record<ArtifactStatus, string> = {
  missing: "var(--text-tertiary)",
  ready_for_review: "var(--gold)",
  approved: "var(--green)",
  rejected: "var(--red)",
};

function StateBadge({scene}: {scene: SceneControlScene}) {
  const color = railColors[scene.rail_status].color;
  return (
    <span
      className="rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide"
      style={{color, border: `1px solid ${color}`, background: "var(--bg-deep)"}}
    >
      {scene.rail_status === "invalidated"
        ? "Invalidated"
        : sceneStateLabel(scene.state)}
    </span>
  );
}

function FilmLockPanel({
  props,
}: {
  props: Pick<
    SceneControlCockpitProps,
    "snapshot" | "busy" | "onReviewFilmLock"
  >;
}) {
  const {snapshot, busy, onReviewFilmLock} = props;
  return (
    <GlassCard className="p-0">
      <div
        className="flex items-start justify-between gap-4 border-b px-4 py-4 sm:px-5"
        style={{borderColor: "var(--border-subtle)"}}
      >
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{color: "var(--turquoise)"}}>
            Film foundations
          </p>
          <h2 className="mt-1 text-base font-bold">Locked across every scene</h2>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold" style={{color: snapshot.film_locks_approved ? "var(--green)" : "var(--gold)"}}>
          {snapshot.film_locks_approved ? <ShieldCheck size={15} /> : <AlertTriangle size={15} />}
          {snapshot.film_locks_approved ? "Approved" : "Review required"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 p-4 sm:grid-cols-2">
        {snapshot.film_locks.map((lock) => (
          <FilmLockEditor
            key={lock.id}
            lock={lock}
            busy={busy}
            onSave={onReviewFilmLock}
          />
        ))}
      </div>
    </GlassCard>
  );
}

function FilmLockEditor({
  lock,
  busy,
  onSave,
}: {
  lock: SceneControlCockpitProps["snapshot"]["film_locks"][number];
  busy?: boolean;
  onSave?: SceneControlCockpitProps["onReviewFilmLock"];
}) {
  const [source, setSource] = useState(() =>
    JSON.stringify(lock.payload ?? {}, null, 2),
  );
  const [error, setError] = useState<string>();

  useEffect(() => {
    setSource(JSON.stringify(lock.payload ?? {}, null, 2));
    setError(undefined);
  }, [lock.payload, lock.revision_hash]);

  const save = () => {
    try {
      const payload = JSON.parse(source) as unknown;
      if (payload === null || typeof payload !== "object") {
        setError("Film-lock payload must be a JSON object or array.");
        return;
      }
      setError(undefined);
      onSave?.(lock.id, payload);
    } catch {
      setError("Enter valid JSON before saving this film lock.");
    }
  };

  return (
    <article
      className="rounded-xl p-3"
      style={{background: "var(--bg-deep)", border: "1px solid var(--border-subtle)"}}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-bold">{lock.label}</h3>
        <span className="text-[10px] font-bold uppercase" style={{color: lock.status === "locked" ? "var(--green)" : lock.status === "invalidated" ? "var(--red)" : "var(--gold)"}}>
          {lock.status}
        </span>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed" style={{color: "var(--text-secondary)"}}>
        {lock.summary}
      </p>
      {onSave ? (
        <details className="mt-3 rounded-lg" style={{border: "1px solid var(--border-subtle)"}}>
          <summary className={`cursor-pointer list-none px-3 py-2 text-[11px] font-bold ${focusRing}`}>
            {lock.status === "locked" ? "Edit canonical payload" : "Establish missing lock"}
          </summary>
          <div className="border-t p-3" style={{borderColor: "var(--border-subtle)"}}>
            <label htmlFor={`${lock.id}-payload`} className="text-[10px] font-bold uppercase" style={{color: "var(--text-tertiary)"}}>
              {lock.label} JSON
            </label>
            <textarea
              id={`${lock.id}-payload`}
              value={source}
              onChange={(event) => setSource(event.target.value)}
              rows={8}
              spellCheck={false}
              className={`mt-2 w-full rounded-lg p-2 font-mono text-[10px] ${focusRing}`}
              style={{background: "var(--bg-void)", border: "1px solid var(--border-subtle)"}}
            />
            {error ? <p className="mt-2 text-[10px]" role="alert" style={{color: "var(--red)"}}>{error}</p> : null}
            <p className="mt-2 text-[10px]" style={{color: "var(--gold)"}}>
              Saves this foundation only. No media or provider generation starts.
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={save}
              className={`mt-2 w-full rounded-lg px-3 py-2 text-[11px] font-bold disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
              style={{background: "var(--turquoise-bg)", color: "var(--turquoise)", border: "1px solid rgba(0,212,170,.2)"}}
            >
              Save and lock {lock.label.toLowerCase()} — no generation
            </button>
          </div>
        </details>
      ) : null}
    </article>
  );
}

function SceneRail({
  scenes,
  selectedId,
  onSelect,
}: {
  scenes: SceneControlScene[];
  selectedId: string;
  onSelect: (sceneId: string) => void;
}) {
  return (
    <nav aria-label="Film scenes" className="overflow-x-auto scrollbar-hide">
      <div className="flex min-w-max gap-2 pb-1">
        {scenes.map((scene) => {
          const locked = scene.rail_status === "locked";
          const selected = scene.id === selectedId;
          const colors = railColors[scene.rail_status];
          return (
            <button
              key={scene.id}
              type="button"
              disabled={locked}
              aria-current={scene.rail_status === "current" ? "step" : undefined}
              aria-pressed={selected}
              aria-describedby={locked ? `${scene.id}-locked` : undefined}
              onClick={() => onSelect(scene.id)}
              className={`min-w-44 rounded-xl p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${focusRing}`}
              style={{
                color: colors.color,
                background: selected ? colors.background : "var(--bg-deep)",
                border: `1px solid ${selected ? colors.color : "var(--border-subtle)"}`,
              }}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-bold uppercase tracking-wide">Scene {scene.number}</span>
                {locked ? <LockKeyhole size={13} aria-hidden /> : scene.rail_status === "accepted" ? <Check size={13} aria-hidden /> : null}
              </span>
              <span className="mt-1 block max-w-36 truncate text-xs font-semibold" style={{color: locked ? "var(--text-tertiary)" : "var(--text-primary)"}}>
                {scene.title}
              </span>
              {locked ? (
                <span id={`${scene.id}-locked`} className="mt-1 block text-[9px]">
                  Prior scene must be accepted
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

function ShotBoard({
  shots,
  selectedId,
  onSelect,
}: {
  shots: SceneControlShot[];
  selectedId: string;
  onSelect: (shotId: string) => void;
}) {
  return (
    <section aria-labelledby="shot-board-heading">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{color: "var(--turquoise)"}}>Synchronous order</p>
          <h2 id="shot-board-heading" className="mt-1 text-base font-bold">Shot board</h2>
        </div>
        <span className="text-xs" style={{color: "var(--text-secondary)"}}>{shots.length} shots</span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {shots.map((shot) => {
          const selected = shot.id === selectedId;
          return (
            <button
              key={shot.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(shot.id)}
              className={`min-w-0 rounded-xl p-3 text-left ${focusRing}`}
              style={{
                background: selected ? "var(--turquoise-bg)" : "var(--bg-deep)",
                border: `1px solid ${selected ? "var(--turquoise)" : "var(--border-subtle)"}`,
              }}
            >
              <span className="flex items-center justify-between gap-2 text-[10px] font-bold uppercase tracking-wide" style={{color: selected ? "var(--turquoise)" : "var(--text-tertiary)"}}>
                Shot {shot.order}
                <span>{shot.duration_seconds}s</span>
              </span>
              <span className="mt-1.5 block text-xs font-semibold leading-snug">{shot.title}</span>
              <span className="mt-2 block text-[10px]" style={{color: shot.performance_mode === "silent_action" ? "var(--gold)" : "var(--text-secondary)"}}>
                {shot.performance_mode.replace("_", " ")}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ShotInspector({shot}: {shot: SceneControlShot}) {
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.2fr_.8fr]">
      <GlassCard className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide" style={{color: "var(--turquoise)"}}>Shot {shot.order} inspection</p>
            <h2 className="mt-1 text-base font-bold">{shot.title}</h2>
          </div>
          <span className="rounded-full px-2 py-1 text-[10px] font-semibold" style={{background: shot.performance_mode === "silent_action" ? "var(--gold-dim)" : "var(--turquoise-bg)", color: shot.performance_mode === "silent_action" ? "var(--gold)" : "var(--turquoise)"}}>
            {shot.performance_mode.replace("_", " ")}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[
            ["Narrative function", shot.narrative_function],
            ["How this advances the film", shot.advancement],
            ["Character action", shot.character_action],
            ["Camera action", shot.camera_action],
            ["Transition", shot.transition],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg p-3" style={{background: "var(--bg-deep)"}}>
              <h3 className="text-[10px] font-bold uppercase tracking-wide" style={{color: "var(--text-tertiary)"}}>{label}</h3>
              <p className="mt-1 text-xs leading-relaxed">{value}</p>
            </div>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg p-3" style={{border: "1px solid var(--border-subtle)"}}>
            <h3 className="text-[10px] font-bold uppercase tracking-wide" style={{color: "var(--text-tertiary)"}}>Opening state</h3>
            <p className="mt-1 text-xs">{shot.opening_state}</p>
          </div>
          <div className="rounded-lg p-3" style={{border: "1px solid rgba(0,212,170,.22)"}}>
            <h3 className="text-[10px] font-bold uppercase tracking-wide" style={{color: "var(--turquoise)"}}>Closing state</h3>
            <p className="mt-1 text-xs">{shot.closing_state}</p>
          </div>
        </div>

        <details className="mt-3 rounded-lg p-3" style={{background: "var(--bg-deep)"}}>
          <summary className={`flex cursor-pointer list-none items-center justify-between text-xs font-semibold ${focusRing}`}>
            Continuity inputs and outputs
            <ChevronDown size={14} aria-hidden />
          </summary>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <p className="text-[10px] font-bold uppercase" style={{color: "var(--text-tertiary)"}}>Inherited</p>
              <ul className="mt-1 list-disc pl-4 text-xs" style={{color: "var(--text-secondary)"}}>
                {shot.continuity_inputs.map((value) => <li key={value}>{value}</li>)}
              </ul>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase" style={{color: "var(--turquoise)"}}>Passed forward</p>
              <ul className="mt-1 list-disc pl-4 text-xs" style={{color: "var(--text-secondary)"}}>
                {shot.continuity_outputs.map((value) => <li key={value}>{value}</li>)}
              </ul>
            </div>
          </div>
        </details>
      </GlassCard>

      <div className="flex flex-col gap-3">
        {shot.preview ? (
          <GlassCard className="p-4">
            <h2 className="flex items-center gap-2 text-sm font-bold">
              <Clapperboard size={15} style={{color: "var(--turquoise)"}} />
              Synthetic comparison shot
            </h2>
            <video
              controls
              preload="metadata"
              src={shot.preview.url}
              className="mt-3 aspect-video w-full rounded-lg bg-black"
            >
              This browser cannot play the synthetic shot proof.
            </video>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
              <div className="rounded-lg p-2" style={{background: "var(--bg-deep)"}}>
                <dt style={{color: "var(--text-tertiary)"}}>Frame evidence</dt>
                <dd className="mt-1 font-mono">{shot.preview.start_frame}–{shot.preview.end_frame}</dd>
              </div>
              <div className="min-w-0 rounded-lg p-2" style={{background: "var(--bg-deep)"}}>
                <dt style={{color: "var(--text-tertiary)"}}>SHA-256</dt>
                <dd className="mt-1 truncate font-mono" title={shot.preview.sha256}>{shot.preview.sha256}</dd>
              </div>
            </dl>
            <p className="mt-3 rounded-lg p-2 text-[10px]" style={{background: "var(--gold-dim)", color: "var(--gold)"}}>
              Comparison media only. This shot preview is not an approved artifact for the current gate.
            </p>
          </GlassCard>
        ) : null}
        <GlassCard className="p-4">
          <h2 className="flex items-center gap-2 text-sm font-bold"><MessageSquareText size={15} style={{color: "var(--turquoise)"}} /> Dialogue and action</h2>
          {shot.dialogue.length ? (
            <ol className="mt-3 flex flex-col gap-2">
              {shot.dialogue.map((line) => (
                <li key={line.id} className="rounded-lg p-3" style={{background: "var(--bg-deep)"}}>
                  <div className="flex items-center justify-between gap-2 text-[10px] font-bold">
                    <span style={{color: "var(--turquoise)"}}>{line.speaker_label}</span>
                    <span style={{color: "var(--text-tertiary)"}}>
                      {line.timing_label ?? `${line.start_seconds.toFixed(1)}–${line.end_seconds.toFixed(1)}s`}
                    </span>
                  </div>
                  <p className="mt-1 text-xs">&ldquo;{line.text}&rdquo;</p>
                  <p className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>{line.performance_intent}</p>
                </li>
              ))}
            </ol>
          ) : (
            <div className="mt-3 rounded-lg p-3" style={{background: "var(--gold-dim)", color: "var(--gold)"}}>
              <p className="text-xs font-semibold">Intentional silent-action beat</p>
              <p className="mt-1 text-[10px]">No dialogue or narration is owned by this shot.</p>
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-4">
          <h2 className="flex items-center gap-2 text-sm font-bold"><Film size={15} style={{color: "var(--turquoise)"}} /> Artifacts</h2>
          <ul className="mt-3 flex flex-col gap-2">
            {shot.artifacts.map((artifact) => (
              <li key={artifact.id} className="flex items-start justify-between gap-3 rounded-lg p-3" style={{background: "var(--bg-deep)"}}>
                <div>
                  <p className="text-xs font-semibold">{artifact.label}</p>
                  {artifact.detail ? <p className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>{artifact.detail}</p> : null}
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-bold uppercase" style={{color: artifactColors[artifact.status]}}>{artifact.status.replaceAll("_", " ")}</p>
                  <p className="mt-1 text-[9px]" style={{color: artifact.deterministic ? "var(--green)" : "var(--gold)"}}>
                    {artifact.deterministic ? "Deterministic" : "Paid stage"}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </GlassCard>
      </div>
    </div>
  );
}

function AssemblyProof({
  scene,
}: {
  scene: SceneControlScene;
}) {
  if (!scene.assembly_preview) return null;
  const current = scene.assembly_preview.current_for_acceptance;
  return (
    <GlassCard className="p-4 sm:p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{color: current ? "var(--green)" : "var(--gold)"}}>
            {current ? "Acceptance evidence" : "Synthetic comparison proof"}
          </p>
          <h2 className="mt-1 text-base font-bold">Assembled Scene {scene.number} proof</h2>
          <p className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>
            {current
              ? `Review the complete deterministic ${(scene.assembly_preview.duration_frames / 24).toFixed(0)}-second assembly before accepting the scene.`
              : "Retained only for comparison. This assembly is not approved for the current gate."}
          </p>
        </div>
        <span className="rounded-full px-2 py-1 text-[10px] font-bold uppercase" style={{background: current ? "var(--green-dim)" : "var(--gold-dim)", color: current ? "var(--green)" : "var(--gold)"}}>
          {scene.assembly_preview.duration_frames} frames · {current ? "current" : "comparison only"}
        </span>
      </div>
      <video
        controls
        preload="metadata"
        src={scene.assembly_preview.url}
        className="mt-4 aspect-video w-full rounded-xl bg-black"
      >
        This browser cannot play the assembled synthetic proof.
      </video>
      <div className="mt-3 rounded-lg p-3 text-[10px]" style={{background: "var(--bg-deep)"}}>
        <p className="font-bold uppercase" style={{color: "var(--text-tertiary)"}}>Assembly provenance · SHA-256</p>
        <p className="mt-1 break-all font-mono">{scene.assembly_preview.sha256}</p>
      </div>
    </GlassCard>
  );
}

function ExactCostCard({
  quote,
}: {
  quote: NonNullable<SceneControlCockpitProps["snapshot"]["next_operation"]>;
}) {
  const operationLabel = {
    storyboard_images: "Generate storyboard images",
    final_imagery: "Generate final imagery",
    animate_shot: "Animate one shot",
    dialogue_audio: "Generate dialogue audio",
    assemble_scene: "Assemble scene in Remotion",
  }[quote.operation_type];
  return (
    <details className="glass-card" open>
      <summary className={`flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-4 ${focusRing}`}>
        <span className="flex items-center gap-2 text-sm font-bold">
          <CircleDollarSign size={17} style={{color: quote.deterministic ? "var(--green)" : "var(--gold)"}} />
          Next operation quote
        </span>
        <span className="text-sm font-bold" style={{color: "var(--turquoise)"}}>
          {formatCents(quote.exact_incremental_max_cents)} max
        </span>
      </summary>
      <div className="border-t px-4 pb-4 pt-3" style={{borderColor: "var(--border-subtle)"}}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-bold">{operationLabel}</p>
            <p className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>
              Scene {quote.scene_number} · {quote.shot_ids.length} shots · {quote.provider_operation.replaceAll("_", " ")}
            </p>
          </div>
          <span className="rounded-full px-2 py-1 text-[10px] font-bold uppercase" style={{background: quote.deterministic ? "var(--green-dim)" : "var(--gold-dim)", color: quote.deterministic ? "var(--green)" : "var(--gold)"}}>
            {quote.deterministic ? "Deterministic · $0" : "Paid · not approved"}
          </span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["Initial calls", String(quote.initial_calls)],
            ["Repair calls", String(quote.max_repair_calls)],
            ["Prior completed", formatCents(quote.prior_completed_cumulative_spend_cents)],
            ["New exact ceiling", formatCents(quote.new_exact_cumulative_ceiling_cents)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg p-2.5" style={{background: "var(--bg-deep)"}}>
              <dt className="text-[9px] font-bold uppercase" style={{color: "var(--text-tertiary)"}}>{label}</dt>
              <dd className="mt-1 text-xs font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="text-[10px] font-bold uppercase" style={{color: "var(--green)"}}>Included</p>
            <ul className="mt-1 list-disc pl-4 text-xs" style={{color: "var(--text-secondary)"}}>
              {quote.included_media.map((value) => <li key={value}>{value}</li>)}
            </ul>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase" style={{color: "var(--red)"}}>Still unapproved</p>
            <ul className="mt-1 list-disc pl-4 text-xs" style={{color: "var(--text-secondary)"}}>
              {quote.explicitly_unapproved.map((value) => <li key={value}>{value}</li>)}
            </ul>
          </div>
        </div>
        <div className="mt-3 rounded-lg p-3 text-xs" role="status" style={{background: "var(--gold-dim)", color: "var(--gold)"}}>
          Quote only. This cockpit has no approval endpoint and cannot start provider work.
        </div>
      </div>
    </details>
  );
}

export function SceneControlCockpit(props: SceneControlCockpitProps) {
  const snapshot = useMemo(
    () => validateSceneControlSnapshot(props.snapshot),
    [props.snapshot],
  );
  const defaultScene = currentScene(snapshot);
  const [selectedSceneId, setSelectedSceneId] = useState(defaultScene.id);
  const selectedScene =
    snapshot.scenes.find(({id}) => id === selectedSceneId) ?? defaultScene;
  const [selectedShotByScene, setSelectedShotByScene] = useState<Record<string, string>>({});
  const selectedShotId =
    selectedShotByScene[selectedScene.id] ?? selectedScene.shots[0].id;
  const selectedShot =
    selectedScene.shots.find(({id}) => id === selectedShotId) ??
    selectedScene.shots[0];
  const nextState = nextSceneState(selectedScene.state);
  const nextEvidenceHash = nextState
    ? selectedScene.transition_evidence_hashes[nextState]
    : undefined;
  const isCurrent = selectedScene.rail_status === "current";
  const transitionDisabled =
    props.busy ||
    !isCurrent ||
    !snapshot.film_locks_approved ||
    nextState === null ||
    !nextEvidenceHash;
  const transitionHelp = !isCurrent
    ? "Only the current scene can transition."
    : !snapshot.film_locks_approved
      ? "Approve every film foundation first."
      : nextState === null
        ? "This scene is already accepted."
        : !nextEvidenceHash
          ? "Required transition evidence is missing."
        : "Transitions are compare-and-set against this exact scene revision.";
  const quoteOperation: Partial<
    Record<
      SceneControlScene["state"],
      "storyboard_images" | "final_imagery" | "animate_shot" | "dialogue_audio" | "assemble_scene"
    >
  > = {
    plan_approved: "storyboard_images",
    storyboard_approved: "final_imagery",
    imagery_approved: "animate_shot",
    animation_approved: "dialogue_audio",
    audio_approved: "assemble_scene",
  };
  const selectedQuoteOperation = quoteOperation[selectedScene.state];

  return (
    <section aria-label="Custom Film Scene Control" className="flex flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em]" style={{color: "var(--turquoise)"}}>
            <Clapperboard size={14} /> Scene Control
          </p>
          <h1 className="mt-1 text-xl font-bold sm:text-2xl">{snapshot.title}</h1>
          <p className="mt-1 text-xs" style={{color: "var(--text-secondary)"}}>
            Human-driven production · one explicit operation at a time
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase">
          <span className="rounded-full px-2.5 py-1" style={{background: "var(--green-dim)", color: "var(--green)"}}>
            Deterministic work labeled
          </span>
          <span className="rounded-full px-2.5 py-1" style={{background: "var(--gold-dim)", color: "var(--gold)"}}>
            Paid work gated
          </span>
        </div>
      </header>

      <FilmLockPanel props={props} />
      <SceneRail
        scenes={snapshot.scenes}
        selectedId={selectedScene.id}
        onSelect={setSelectedSceneId}
      />

      <GlassCard className="p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide" style={{color: "var(--text-tertiary)"}}>
              Scene {selectedScene.number} · {selectedScene.story_time}
            </p>
            <h2 className="mt-1 text-lg font-bold">{selectedScene.title}</h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed" style={{color: "var(--text-secondary)"}}>
              {selectedScene.purpose}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge scene={selectedScene} />
            <span className="rounded-full px-2 py-1 text-[10px]" style={{background: "var(--bg-deep)", color: "var(--text-secondary)"}}>
              {selectedScene.target_duration_seconds}s · {selectedScene.environment_label}
            </span>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {selectedScene.character_labels.map((character) => (
            <span key={character} className="rounded-full px-2 py-1 text-[10px]" style={{background: "var(--turquoise-bg)", color: "var(--turquoise)"}}>
              {character}
            </span>
          ))}
        </div>
        {selectedScene.invalidation_reason ? (
          <div className="mt-3 rounded-lg p-3 text-xs" role="alert" style={{background: "var(--red-dim)", color: "var(--red)"}}>
            {selectedScene.invalidation_reason}
          </div>
        ) : null}
      </GlassCard>

      <ShotBoard
        shots={selectedScene.shots}
        selectedId={selectedShot.id}
        onSelect={(shotId) =>
          setSelectedShotByScene((previous) => ({
            ...previous,
            [selectedScene.id]: shotId,
          }))
        }
      />
      <ShotInspector shot={selectedShot} />
      <AssemblyProof scene={selectedScene} />

      {snapshot.next_operation?.scene_id === selectedScene.id ? (
        <ExactCostCard quote={snapshot.next_operation} />
      ) : selectedQuoteOperation && isCurrent && props.onRequestQuote ? (
        <GlassCard className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-bold">
                <CircleDollarSign size={16} style={{color: "var(--gold)"}} />
                Exact next-operation cost
              </h2>
              <p className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>
                Requesting a quote is read-only and starts no provider work.
              </p>
            </div>
            <button
              type="button"
              disabled={props.busy}
              onClick={() =>
                props.onRequestQuote?.({
                  scene_id: selectedScene.id,
                  shot_id:
                    selectedQuoteOperation === "animate_shot"
                      ? selectedShot.id
                      : undefined,
                  expected_revision_hash: selectedScene.revision_hash,
                  operation_type: selectedQuoteOperation,
                })
              }
              className={`rounded-xl px-4 py-2.5 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
              style={{background: "var(--gold-dim)", color: "var(--gold)", border: "1px solid rgba(212,168,82,.25)"}}
            >
              Show exact quote — no generation
            </button>
          </div>
        </GlassCard>
      ) : null}

      <GlassCard className="p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-bold">
              <Sparkles size={15} style={{color: "var(--turquoise)"}} />
              Explicit scene transition
            </h2>
            <p id="scene-transition-help" className="mt-1 text-[10px]" style={{color: "var(--text-secondary)"}}>
              {transitionHelp}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            {selectedScene.state !== "draft" && selectedScene.state !== "accepted" ? (
              <button
                type="button"
                disabled={props.busy || !isCurrent}
                onClick={() =>
                  props.onReject({
                    scene_id: selectedScene.id,
                    shot_id: selectedShot.id,
                    return_to: previousReviewState(selectedScene.state),
                    expected_revision_hash: selectedScene.revision_hash,
                  })
                }
                className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
                style={{background: "var(--red-dim)", color: "var(--red)", border: "1px solid rgba(255,77,106,.24)"}}
              >
                <RotateCcw size={15} />
                Reject shot to prior gate
              </button>
            ) : null}
            <button
              type="button"
              disabled={transitionDisabled}
              aria-describedby="scene-transition-help"
              onClick={() => {
                if (!nextState || !nextEvidenceHash) return;
                props.onTransition({
                  scene_id: selectedScene.id,
                  from_state: selectedScene.state,
                  to_state: nextState,
                  expected_revision_hash: selectedScene.revision_hash,
                  evidence_hash: nextEvidenceHash,
                });
              }}
              className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
              style={{background: "var(--turquoise)", color: "var(--bg-void)"}}
            >
              {selectedScene.state === "audio_approved" ? <Volume2 size={15} /> : <Check size={15} />}
              {nextState ? transitionLabel(selectedScene.state, nextState) : "Scene accepted"}
            </button>
          </div>
        </div>
      </GlassCard>
    </section>
  );
}
