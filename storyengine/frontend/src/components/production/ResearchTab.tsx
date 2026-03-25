"use client";

import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

interface ResearchTabProps {
  video: Video;
}

const MOCK_RESEARCH: Record<string, string> = {
  thesis: "Iran's strategic miscalculation in 2024 was not a failure of intelligence but a textbook example of the Thucydides Trap — where a rising regional power's ambitions collide with an established hegemon's need to maintain order, making conflict structurally inevitable regardless of individual actors' intentions.",
  executiveHook: "In the shadow of a crumbling empire, one decision would reshape the balance of power across three continents — and almost nobody saw it coming. This is the story of how Iran fell for the oldest trap in geopolitics.",
  factSheet: "• 16 of the last 500 years' major power transitions match the Thucydides Trap pattern (Graham Allison, Harvard)\n• Iran's oil exports dropped 47% between 2018-2024 under sanctions pressure\n• The 2024 diplomatic overture involved 3 secret back-channel negotiations over 8 months\n• China's Belt and Road investment in Iran totaled $12.3B by 2023\n• The IRGC's annual budget increased 340% between 2015-2024",
  historicalParallels: "• Peloponnesian War (431 BC): Athens' rise vs Sparta's dominance — the original Thucydides Trap\n• WWI (1914): Germany's industrial rise vs British naval supremacy\n• Cold War Cuban Missile Crisis (1962): Superpower brinkmanship where miscalculation nearly triggered nuclear war",
  frameworkAnalysis: "The Thucydides Trap framework (Graham Allison, 2017) identifies 16 cases over 500 years where a rising power threatened to displace a ruling one. In 12 of those 16 cases, the result was war. The framework reveals structural pressures that make rational actors behave irrationally.",
  characterDossier: "• Esmail Qaani — Soleimani's successor, methodical, risk-averse, but institutionally committed to expansion\n• The unnamed diplomat — Senior Iranian Foreign Ministry official who championed the 2024 overture\n• The intelligence analyst — American NSC advisor who recognized the historical pattern",
  narrativeArc: "ACT 1 (Hook): The secret meeting in Tehran — tension, stakes, betrayal\nACT 2 (Context): Rewind to the Thucydides Trap framework\nACT 3 (Escalation): Iran's strategic position and miscalculations\nACT 4 (Climax): The moment of no return\nACT 5 (Consequences): Economic and geopolitical fallout\nACT 6 (Future): What this means for the next decade",
  counterArguments: "• Critics argue the Thucydides Trap is overly deterministic — agency matters\n• Some scholars point to the 4 cases where war was avoided\n• Iran's decision-making may have been more rational than it appears",
  visualSeeds: "• Dark Tehran cityscape at night with surveillance overlay\n• Split-screen: ancient Greek columns vs modern missile systems\n• Redacted intelligence documents with highlighted key phrases\n• Map of the Middle East with radiating influence zones",
  themes: "Power transition theory, structural realism, historical determinism vs agency, the fog of war, economic coercion as statecraft",
  psychologicalAngles: "• Fear: 'Could this pattern repeat with China and the US?'\n• Curiosity: 'What was in those secret back-channel messages?'\n• Pattern recognition: 'The same mistake, repeated across 2,500 years'",
  sources: "Graham Allison, 'Destined for War' (2017) · Reuters Special Report (2024) · Financial Times Intelligence Analysis · RAND Corporation Policy Brief · Congressional Research Service Report · IISS Strategic Dossier",
};

const FIELDS: { key: string; label: string; color: string; fullWidth?: boolean }[] = [
  { key: "thesis", label: "Thesis", color: "var(--turquoise)", fullWidth: true },
  { key: "executiveHook", label: "Executive Hook", color: "var(--orange)", fullWidth: true },
  { key: "factSheet", label: "Fact Sheet", color: "var(--green)" },
  { key: "historicalParallels", label: "Historical Parallels", color: "var(--gold)" },
  { key: "frameworkAnalysis", label: "Framework Analysis", color: "var(--purple)" },
  { key: "characterDossier", label: "Character Dossier", color: "var(--turquoise)" },
  { key: "narrativeArc", label: "Narrative Arc", color: "var(--orange)", fullWidth: true },
  { key: "counterArguments", label: "Counter Arguments", color: "var(--red)" },
  { key: "visualSeeds", label: "Visual Seeds", color: "var(--purple)" },
  { key: "themes", label: "Themes", color: "var(--turquoise)" },
  { key: "psychologicalAngles", label: "Psychological Angles", color: "var(--gold)" },
  { key: "sources", label: "Sources", color: "var(--text-secondary)", fullWidth: true },
];

export function ResearchTab({ video }: ResearchTabProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {FIELDS.map((field) => (
          <GlassCard
            key={field.key}
            className={`p-5 ${field.fullWidth ? "md:col-span-2" : ""}`}
            style={{ borderLeftWidth: 3, borderLeftColor: field.color }}
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: field.color }}>
              {field.label}
            </p>
            <p className={`text-sm leading-relaxed whitespace-pre-line ${field.key === "sources" ? "font-mono text-xs" : ""}`} style={{ color: "var(--text-primary)" }}>
              {MOCK_RESEARCH[field.key]}
            </p>
          </GlassCard>
        ))}
      </div>
      <div className="flex gap-3 justify-center pt-4">
        <ActionButton variant="outline">Re-research</ActionButton>
        <ActionButton variant="filled">Export to Google Docs</ActionButton>
      </div>
    </div>
  );
}
