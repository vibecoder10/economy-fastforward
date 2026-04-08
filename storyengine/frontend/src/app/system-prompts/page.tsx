"use client";

import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSystemPrompts, updateSystemPrompt, resetSystemPrompt } from "@/lib/api";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { Loader2 } from "lucide-react";

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.06 } } };
const item = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } };

export default function SystemPromptsPage() {
  const queryClient = useQueryClient();
  const { data: prompts, isLoading, error } = useQuery({
    queryKey: ["system-prompts"],
    queryFn: getSystemPrompts,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--text-tertiary)" }} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-20" style={{ color: "var(--text-tertiary)" }}>
        Failed to load system prompts.
      </div>
    );
  }

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          System Prompts
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Customize the AI system prompts used across your pipeline. Changes here become the default for all new videos.
        </p>
      </motion.div>

      <motion.div variants={item} className="space-y-3">
        {prompts?.map((p) => (
          <SystemPromptEditor
            key={p.key}
            label={`${p.label} System Prompt`}
            currentValue={p.is_custom ? p.prompt : null}
            saveLabel="Save as Default"
            onSave={async (text) => {
              await updateSystemPrompt(p.key, text);
              queryClient.invalidateQueries({ queryKey: ["system-prompts"] });
            }}
            onReset={async () => {
              const res = await resetSystemPrompt(p.key);
              queryClient.invalidateQueries({ queryKey: ["system-prompts"] });
              return res.prompt;
            }}
          />
        ))}
      </motion.div>
    </motion.div>
  );
}
