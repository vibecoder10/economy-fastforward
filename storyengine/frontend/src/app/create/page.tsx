"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { createIdea } from "@/lib/api";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

export default function CreateVideoPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [thesis, setThesis] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pastContext, setPastContext] = useState("");
  const [futurePrediction, setFuturePrediction] = useState("");
  const [openingHook, setOpeningHook] = useState("");
  const [targetLength, setTargetLength] = useState(15);

  const createMutation = useMutation({
    mutationFn: () => {
      // Build topic string from form fields
      const topic = [
        `Title: ${title}`,
        `Angle: ${angle}`,
        `Thesis: ${thesis}`,
        pastContext ? `Past Context: ${pastContext}` : "",
        futurePrediction ? `Future Prediction: ${futurePrediction}` : "",
        openingHook ? `Opening Hook: ${openingHook}` : "",
        `Target Length: ${targetLength} minutes`,
      ]
        .filter(Boolean)
        .join("\n");
      return createIdea(topic, "web_ui");
    },
    onSuccess: () => {
      router.push("/pipeline");
    },
  });

  const isValid = title.trim() && angle.trim() && thesis.trim();

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-1 text-sm mb-4 transition-colors hover:opacity-80"
          style={{ color: "var(--text-muted)" }}
        >
          <ArrowLeft size={16} />
          Back
        </Link>

        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          What's Your Story?
        </h1>
        <p className="mt-1" style={{ color: "var(--text-secondary)" }}>
          Every great video starts with a compelling idea.
        </p>
      </div>

      {/* Form */}
      <div className="space-y-5">
        <FormField label="Title" required>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="The AI Chip Shortage That Could Crash the Economy"
            className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        <FormField label="Angle" required>
          <textarea
            value={angle}
            onChange={(e) => setAngle(e.target.value)}
            placeholder="Most people think AI is just software, but the real bottleneck is hardware"
            rows={2}
            className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        <FormField label="Thesis" required>
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            placeholder="The global AI boom depends on a handful of chip fabs..."
            rows={3}
            className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        {/* Advanced options */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-sm font-medium"
          style={{ color: "var(--amber)" }}
        >
          {showAdvanced ? "▲ Hide" : "▼ Show"} Advanced Options
        </button>

        {showAdvanced && (
          <div className="space-y-5 pl-4" style={{ borderLeft: "2px solid var(--border)" }}>
            <FormField label="Past Context">
              <textarea
                value={pastContext}
                onChange={(e) => setPastContext(e.target.value)}
                placeholder="Historical context..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Future Prediction">
              <textarea
                value={futurePrediction}
                onChange={(e) => setFuturePrediction(e.target.value)}
                placeholder="What happens next..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Opening Hook">
              <textarea
                value={openingHook}
                onChange={(e) => setOpeningHook(e.target.value)}
                placeholder="The first 15 seconds..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Target Length">
              <div className="flex gap-2">
                {[5, 10, 15, 20].map((mins) => (
                  <button
                    key={mins}
                    onClick={() => setTargetLength(mins)}
                    className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                    style={{
                      background: targetLength === mins ? "var(--amber)" : "var(--bg-card)",
                      color: targetLength === mins ? "var(--bg-primary)" : "var(--text-secondary)",
                      border: `1px solid ${targetLength === mins ? "var(--amber)" : "var(--border)"}`,
                    }}
                  >
                    {mins} min
                  </button>
                ))}
              </div>
            </FormField>
          </div>
        )}
      </div>

      {/* Submit */}
      <button
        onClick={() => createMutation.mutate()}
        disabled={!isValid || createMutation.isPending}
        className="w-full py-3 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
        style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
      >
        {createMutation.isPending ? "Creating..." : "Generate Story →"}
      </button>

      {createMutation.isError && (
        <p className="text-sm text-center" style={{ color: "var(--red)" }}>
          Failed to create video. Please try again.
        </p>
      )}
    </div>
  );
}

function FormField({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-sm font-medium mb-2 block" style={{ color: "var(--text-primary)" }}>
        {label}
        {required && <span style={{ color: "var(--amber)" }}> *</span>}
      </label>
      {children}
    </div>
  );
}
