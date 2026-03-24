"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { advanceVideo, rejectVideo } from "@/lib/api";
import { ChevronDown, ChevronRight } from "lucide-react";

interface InfoTabProps {
  video: any;
}

export function InfoTab({ video }: InfoTabProps) {
  const [researchOpen, setResearchOpen] = useState(false);
  const queryClient = useQueryClient();

  const advanceMutation = useMutation({
    mutationFn: () => advanceVideo(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectVideo(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  // Parse Story Bible JSON
  let storyBible: any = null;
  if (video.story_bible) {
    try {
      storyBible = typeof video.story_bible === "string"
        ? JSON.parse(video.story_bible)
        : video.story_bible;
    } catch { /* ignore parse errors */ }
  }

  return (
    <div className="space-y-6">
      {/* Story DNA */}
      <Section title="Story DNA">
        <Field label="Framework" value={video.framework_angle} />
        <Field label="Thesis" value={video.thesis} />
        <Field label="Opening Hook" value={video.hook_script} />
        <Field label="Past Context" value={video.past_context} />
        <Field label="Present Parallel" value={video.present_parallel} />
        <Field label="Future Prediction" value={video.future_prediction} />
        {video.writer_guidance && (
          <Field label="Writer Guidance" value={video.writer_guidance} />
        )}
      </Section>

      {/* Story Bible */}
      {storyBible && (
        <Section title="Story Bible">
          {storyBible.characters?.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Characters
              </h4>
              <div className="space-y-2">
                {storyBible.characters.map((c: any, i: number) => (
                  <div key={i} className="flex items-start gap-3">
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                      style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                    >
                      {(c.name || "?")[0]}
                    </div>
                    <div>
                      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {c.name} <span style={{ color: "var(--text-muted)" }}>({c.role || c.archetype || "Character"})</span>
                      </p>
                      {c.visual && (
                        <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                          {c.visual}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {storyBible.locations?.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Locations
              </h4>
              <ul className="space-y-1">
                {storyBible.locations.map((loc: any, i: number) => (
                  <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    {typeof loc === "string" ? loc : loc.name || loc.location}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {storyBible.visual_arc?.length > 0 && (
            <div>
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Visual Arc
              </h4>
              <ul className="space-y-1">
                {storyBible.visual_arc.map((arc: any, i: number) => (
                  <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    Act {i + 1}: {typeof arc === "string" ? arc : arc.description || JSON.stringify(arc)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>
      )}

      {/* Research (collapsible) */}
      {video.research_payload && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <button
            onClick={() => setResearchOpen(!researchOpen)}
            className="flex items-center justify-between w-full p-4 text-left"
          >
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Research Payload
            </span>
            {researchOpen ? (
              <ChevronDown size={16} style={{ color: "var(--text-muted)" }} />
            ) : (
              <ChevronRight size={16} style={{ color: "var(--text-muted)" }} />
            )}
          </button>
          {researchOpen && (
            <div className="px-4 pb-4">
              <pre
                className="text-xs overflow-x-auto whitespace-pre-wrap"
                style={{ color: "var(--text-secondary)" }}
              >
                {typeof video.research_payload === "string"
                  ? video.research_payload
                  : JSON.stringify(video.research_payload, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <Section title="Actions">
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => advanceMutation.mutate()}
            disabled={advanceMutation.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {advanceMutation.isPending ? "Advancing..." : "Approve & Advance →"}
          </button>
          <button
            onClick={() => rejectMutation.mutate()}
            disabled={rejectMutation.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{
              background: "transparent",
              color: "var(--red)",
              border: "1px solid var(--red)",
            }}
          >
            {rejectMutation.isPending ? "Rejecting..." : "Reject & Regenerate"}
          </button>
        </div>
        {(advanceMutation.isError || rejectMutation.isError) && (
          <p className="text-sm mt-2" style={{ color: "var(--red)" }}>
            Action failed. Please try again.
          </p>
        )}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <h3
        className="text-sm font-semibold uppercase tracking-wider mb-3"
        style={{ color: "var(--text-muted)" }}
      >
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="mb-3 last:mb-0">
      <dt className="text-xs font-medium mb-0.5" style={{ color: "var(--text-muted)" }}>
        {label}
      </dt>
      <dd className="text-sm" style={{ color: "var(--text-primary)" }}>
        {value}
      </dd>
    </div>
  );
}
