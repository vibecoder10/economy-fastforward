"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { createIdea } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

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

  const inputStyle = {
    background: "var(--bg-elevated)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  const handleFocus = (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    e.target.style.borderColor = "var(--turquoise)";
  };
  const handleBlur = (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    e.target.style.borderColor = "var(--border)";
  };

  return (
    <motion.div
      className="max-w-2xl mx-auto space-y-6"
      variants={container}
      initial="hidden"
      animate="show"
    >
      {/* Header */}
      <motion.div variants={item}>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-1 text-sm mb-4 transition-colors hover:opacity-80 font-body"
          style={{ color: "var(--text-muted)" }}
        >
          <ArrowLeft size={16} />
          Back
        </Link>

        <h1 className="text-2xl font-display" style={{ color: "var(--text-primary)" }}>
          What&apos;s Your Story?
        </h1>
        <p className="mt-1 font-body" style={{ color: "var(--text-secondary)" }}>
          Every great video starts with a compelling idea.
        </p>
      </motion.div>

      {/* Form */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="space-y-5">
            <FormField label="Title" required>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="The AI Chip Shortage That Could Crash the Economy"
                className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none transition-all"
                style={inputStyle}
                onFocus={handleFocus}
                onBlur={handleBlur}
              />
            </FormField>

            <FormField label="Angle" required>
              <textarea
                value={angle}
                onChange={(e) => setAngle(e.target.value)}
                placeholder="Most people think AI is just software, but the real bottleneck is hardware"
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none resize-none transition-all"
                style={inputStyle}
                onFocus={handleFocus}
                onBlur={handleBlur}
              />
            </FormField>

            <FormField label="Thesis" required>
              <textarea
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                placeholder="The global AI boom depends on a handful of chip fabs..."
                rows={3}
                className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none resize-none transition-all"
                style={inputStyle}
                onFocus={handleFocus}
                onBlur={handleBlur}
              />
            </FormField>

            {/* Advanced options */}
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-sm font-medium font-body transition-colors hover:brightness-110"
              style={{ color: "var(--turquoise)" }}
            >
              {showAdvanced ? "Hide" : "Show"} Advanced Options
            </button>

            {showAdvanced && (
              <div className="space-y-5 pl-4" style={{ borderLeft: "2px solid var(--turquoise)", borderLeftColor: "rgba(0, 212, 170, 0.3)" }}>
                <FormField label="Past Context">
                  <textarea
                    value={pastContext}
                    onChange={(e) => setPastContext(e.target.value)}
                    placeholder="Historical context..."
                    rows={2}
                    className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none resize-none transition-all"
                    style={inputStyle}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                  />
                </FormField>

                <FormField label="Future Prediction">
                  <textarea
                    value={futurePrediction}
                    onChange={(e) => setFuturePrediction(e.target.value)}
                    placeholder="What happens next..."
                    rows={2}
                    className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none resize-none transition-all"
                    style={inputStyle}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                  />
                </FormField>

                <FormField label="Opening Hook">
                  <textarea
                    value={openingHook}
                    onChange={(e) => setOpeningHook(e.target.value)}
                    placeholder="The first 15 seconds..."
                    rows={2}
                    className="w-full rounded-lg px-4 py-3 text-sm font-body outline-none resize-none transition-all"
                    style={inputStyle}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                  />
                </FormField>

                <FormField label="Target Length">
                  <div className="flex gap-2">
                    {[5, 10, 15, 20].map((mins) => (
                      <button
                        key={mins}
                        onClick={() => setTargetLength(mins)}
                        className="px-4 py-2 rounded-full text-sm font-medium font-body transition-all"
                        style={{
                          background: targetLength === mins ? "var(--turquoise)" : "var(--bg-elevated)",
                          color: targetLength === mins ? "var(--bg-void)" : "var(--text-secondary)",
                          border: `1px solid ${targetLength === mins ? "var(--turquoise)" : "var(--border)"}`,
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
        </GlassCard>
      </motion.div>

      {/* Submit */}
      <motion.div variants={item}>
        <ActionButton
          onClick={() => createMutation.mutate()}
          disabled={!isValid || createMutation.isPending}
          variant="filled"
          className="!w-full !py-3 !rounded-xl"
        >
          {createMutation.isPending ? "Creating..." : "Generate Story"}
        </ActionButton>
      </motion.div>

      {createMutation.isError && (
        <motion.p
          variants={item}
          className="text-sm text-center font-body"
          style={{ color: "var(--red)" }}
        >
          Failed to create video. Please try again.
        </motion.p>
      )}
    </motion.div>
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
      <label className="text-sm font-medium mb-2 block font-body" style={{ color: "var(--text-primary)" }}>
        {label}
        {required && <span style={{ color: "var(--turquoise)" }}> *</span>}
      </label>
      {children}
    </div>
  );
}
