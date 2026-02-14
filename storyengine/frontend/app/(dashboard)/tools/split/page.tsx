"use client";

import { useState } from "react";

interface Segment {
  segmentIndex: number;
  segmentText: string;
  durationSeconds: number;
  visualConcept: string;
  shotType: string;
  imagePrompt: string;
}

export default function SplitToolPage() {
  const [sceneText, setSceneText] = useState("");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<unknown>(null);

  async function handleSplit() {
    if (!sceneText.trim()) return;

    setLoading(true);
    setError(null);
    setDebugInfo(null);
    setSegments([]);

    try {
      const res = await fetch("/api/agents/segment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sceneText: sceneText.trim() }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || "Request failed");
        if (data.debug) {
          setDebugInfo(data.debug);
        }
        return;
      }

      setSegments(data.segments || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error");
    } finally {
      setLoading(false);
    }
  }

  function handleMerge(indexA: number, indexB: number) {
    setSegments((prev) => {
      const next = [...prev];
      const a = next[indexA];
      const b = next[indexB];
      if (!a || !b) return prev;

      next[indexA] = {
        ...a,
        segmentText: a.segmentText + " " + b.segmentText,
        durationSeconds:
          Math.round((a.durationSeconds + b.durationSeconds) * 10) / 10,
        visualConcept: a.visualConcept,
        imagePrompt: a.imagePrompt,
      };
      next.splice(indexB, 1);

      // Re-index
      return next.map((s, i) => ({ ...s, segmentIndex: i + 1 }));
    });
  }

  function handleSplitSegment(index: number) {
    setSegments((prev) => {
      const seg = prev[index];
      if (!seg) return prev;

      const sentences = seg.segmentText.match(/[^.!?]+[.!?]+/g) || [
        seg.segmentText,
      ];
      if (sentences.length < 2) return prev;

      const midpoint = Math.ceil(sentences.length / 2);
      const textA = sentences.slice(0, midpoint).join(" ").trim();
      const textB = sentences.slice(midpoint).join(" ").trim();
      const wordsA = textA.split(/\s+/).length;
      const wordsB = textB.split(/\s+/).length;

      const next = [...prev];
      next.splice(
        index,
        1,
        {
          ...seg,
          segmentText: textA,
          durationSeconds: Math.round(((wordsA / 173) * 60) * 10) / 10,
          visualConcept: seg.visualConcept,
        },
        {
          ...seg,
          segmentText: textB,
          durationSeconds: Math.round(((wordsB / 173) * 60) * 10) / 10,
          visualConcept: seg.visualConcept + " (continued)",
          imagePrompt: "[Needs regeneration after split]",
        }
      );

      return next.map((s, i) => ({ ...s, segmentIndex: i + 1 }));
    });
  }

  const totalDuration = segments.reduce(
    (sum, s) => sum + s.durationSeconds,
    0
  );

  return (
    <div className="max-w-6xl">
      <h1 className="text-3xl font-bold mb-2">Split / Merge Tool</h1>
      <p className="text-text-secondary mb-6">
        Paste scene narration below. Claude segments it by visual concept and
        generates image prompts for each segment.
      </p>

      {/* Input */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-text-secondary mb-2">
          Scene Narration
        </label>
        <textarea
          rows={8}
          className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent resize-y font-body text-sm leading-relaxed"
          placeholder="Paste the full narration text for one scene here..."
          value={sceneText}
          onChange={(e) => setSceneText(e.target.value)}
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-text-tertiary">
            {sceneText.split(/\s+/).filter(Boolean).length} words
            {" | "}
            ~{Math.round((sceneText.split(/\s+/).filter(Boolean).length / 173) * 60)}s
          </span>
          <button
            onClick={handleSplit}
            disabled={loading || !sceneText.trim()}
            className="px-6 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-background font-semibold rounded-lg transition-colors"
          >
            {loading ? "Splitting..." : "Split with Claude"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-red-900/20 border border-error/30 rounded-lg">
          <p className="text-error font-medium text-sm">{error}</p>
          {debugInfo && (
            <details className="mt-3">
              <summary className="text-xs text-text-tertiary cursor-pointer">
                Debug info
              </summary>
              <pre className="mt-2 text-xs text-text-secondary overflow-x-auto whitespace-pre-wrap font-mono">
                {JSON.stringify(debugInfo, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* Results */}
      {segments.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">
              {segments.length} Segments
              <span className="text-text-tertiary font-normal ml-2">
                ({Math.round(totalDuration)}s total)
              </span>
            </h2>
            <p className="text-xs text-text-tertiary">
              Check your browser console (F12) and your server terminal for full
              API call logs
            </p>
          </div>

          <div className="space-y-3">
            {segments.map((seg, idx) => (
              <div
                key={seg.segmentIndex}
                className="border border-border rounded-xl overflow-hidden"
              >
                {/* Header */}
                <div className="flex items-center gap-3 px-4 py-2.5 bg-surface border-b border-border">
                  <span className="text-xs font-mono font-bold text-accent">
                    #{seg.segmentIndex}
                  </span>
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-surface-hover text-text-secondary uppercase tracking-wider">
                    {seg.shotType}
                  </span>
                  <span className="text-xs text-text-tertiary">
                    {seg.durationSeconds}s
                  </span>
                  <span className="text-xs text-text-tertiary ml-auto">
                    {seg.segmentText.split(/\s+/).length} words
                  </span>
                  <div className="flex gap-1">
                    <button
                      onClick={() => handleSplitSegment(idx)}
                      className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-hover text-text-secondary transition-colors"
                      title="Split this segment"
                    >
                      Split
                    </button>
                    {idx < segments.length - 1 && (
                      <button
                        onClick={() => handleMerge(idx, idx + 1)}
                        className="px-2 py-1 text-xs border border-border rounded hover:bg-surface-hover text-text-secondary transition-colors"
                        title="Merge with next segment"
                      >
                        Merge ↓
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 divide-x divide-border">
                  {/* Narration Text */}
                  <div className="p-4">
                    <p className="text-xs font-medium text-text-tertiary mb-1.5 uppercase tracking-wider">
                      Narration
                    </p>
                    <p className="text-sm text-text-primary leading-relaxed">
                      {seg.segmentText}
                    </p>
                    <p className="mt-2 text-xs text-text-tertiary italic">
                      {seg.visualConcept}
                    </p>
                  </div>

                  {/* Image Prompt */}
                  <div className="p-4">
                    <p className="text-xs font-medium text-text-tertiary mb-1.5 uppercase tracking-wider">
                      Visual Prompt
                    </p>
                    <p className="text-sm text-text-secondary leading-relaxed font-mono">
                      {seg.imagePrompt}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
