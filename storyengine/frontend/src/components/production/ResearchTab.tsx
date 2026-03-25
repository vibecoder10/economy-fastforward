"use client";

import { RefreshCw, FileText } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

const MOCK_RESEARCH: Record<string, string> = {
  headline: "Iran's Shadow Empire: How Sanctions Built a $400B Parallel Economy",
  thesis:
    "Western sanctions against Iran, intended to cripple its economy, inadvertently catalyzed the creation of a sophisticated parallel financial infrastructure. The IRGC-controlled conglomerates now manage over 40% of non-oil GDP, while China's Belt and Road Initiative provided the critical bypass to SWIFT-based sanctions enforcement. Three decades of economic warfare created the very resilience the West sought to prevent.",
  executiveHook:
    "What if the most devastating sanctions regime in history didn't weaken Iran — but made it stronger? In the shadowed corridors of Tehran, a $400 billion shadow economy has been quietly growing, invisible to Western intelligence, powered by an unlikely alliance with Beijing.",
  factSheet:
    "- Iran's GDP contracted 12.6% in 2018 following reimposed US sanctions (IMF)\n- IRGC-linked companies control an estimated 40-50% of Iran's non-oil GDP ($180B+)\n- The Iran-China 25-year cooperation agreement is worth an estimated $400B\n- Iran's parallel banking network processes ~$12B annually outside SWIFT\n- The rial lost 80% of its value between 2018-2020\n- Iran holds the world's 2nd largest natural gas reserves (33.8 trillion cubic meters)\n- Chabahar port handles 8.5M tons of cargo annually, bypassing the Strait of Hormuz\n- The IRGC controls 27 ports, 30+ construction firms, and a telecom network\n- Iran's cryptocurrency mining consumes 4.5% of national electricity output\n- Barter trade with Turkey, Iraq, and Afghanistan totals ~$8B/year",
  historicalParallels:
    "- Soviet Union (1979-1991): US grain embargo led USSR to develop Central Asian agriculture, becoming self-sufficient within 5 years. Parallel to Iran's agricultural pivot after food import sanctions.\n- Cuba (1962-present): 60+ years of US embargo forced Cuba to develop biotechnology sector worth $800M/year. Iran similarly pivoted to domestic pharmaceutical production.\n- Rhodesia (1965-1979): UN sanctions on Rhodesia led to 'sanctions-busting' networks through South Africa, Mozambique — remarkably similar to Iran's networks through UAE, Turkey, and Iraq.\n- North Korea (2006-present): DPRK's cryptocurrency operations and shell company networks mirror Iran's digital asset strategies for sanctions evasion.",
  frameworkAnalysis:
    "Through a Machiavellian lens, Iran's response to sanctions represents a masterclass in strategic adaptation. The IRGC transformed from a military force into a corporate empire not despite sanctions, but because of them. Each new restriction created a market gap that regime-connected entities filled, concentrating wealth and power in the very institutions the West sought to weaken. The framework reveals a paradox: maximum pressure created maximum incentive for regime entrenchment.",
  characterDossier:
    "- Qasem Soleimani (d. 2020): IRGC Quds Force commander who built the economic warfare playbook. Personally negotiated the Iraq oil-for-goods corridor. Visual: military uniform, piercing gaze, map of Middle East behind him.\n- Mohsen Rezaei: Former IRGC commander turned economic strategist. Architect of the 'Resistance Economy' doctrine. Visual: suited figure at podium, economic charts behind him.\n- Wang Yi: Chinese Foreign Minister who signed the 25-year cooperation deal. The quiet enabler. Visual: diplomatic handshake, silk road map overlay.\n- Abdolnaser Hemmati: Former Central Bank governor who managed the parallel currency system. Visual: office with multiple screens showing exchange rates.",
  narrativeArc:
    "ACT 1 (HOOK): Open with the sanctions paradox — the West's most powerful economic weapon may have backfired. ACT 2 (CONTEXT): Historical sweep of US-Iran economic warfare from 1979 to present. ACT 3 (MECHANISM): Deep dive into how the IRGC built its corporate empire in the gaps sanctions created. ACT 4 (ALLIANCE): The China pivot — Belt and Road as sanctions bypass. ACT 5 (SCALE): The $400B shadow economy revealed — parallel banking, crypto mining, barter networks. ACT 6 (IMPLICATIONS): Has the West created the very monster it sought to contain?",
  counterArguments:
    "- Sanctions DID reduce Iran's oil exports from 2.5M to 400K barrels/day — the economy IS smaller\n- The parallel economy enriches the IRGC, not ordinary Iranians — living standards have declined\n- China's commitment is uncertain — Beijing's investments often underdeliver\n- Iran's crypto strategy is vulnerable to blockchain surveillance improvements\nRebuttal: While sanctions achieved tactical goals (reduced oil revenue), they failed strategically by consolidating IRGC power and pushing Iran into China's orbit — a far worse outcome for US interests.",
  visualSeeds:
    "- Darkened war room with scattered maps and documents (dossier style)\n- Split screen: collapsing rial chart vs. rising IRGC revenue\n- Aerial shot of Chabahar port with container ships\n- Tehran skyline at night transitioning to Beijing\n- Network diagram: IRGC shell company web\n- Historical montage: 1979 revolution to 2018 sanctions reimposed\n- Gold bars and cryptocurrency symbols on dark background",
  themes:
    "- Economic Blowback Theory: how punitive measures create unintended resilience\n- Shadow State Capitalism: the merger of military and commercial power\n- Multipolar Finance: the erosion of dollar hegemony through alternative systems\n- Strategic Patience: Iran's multi-generational approach vs. Western electoral cycles",
  psychologicalAngles:
    '- Fear: "What if sanctions are making enemies stronger, not weaker?"\n- Curiosity: "How does $12B move through the global system without anyone noticing?"\n- Outrage: "Your tax dollars funded a sanctions regime that backfired spectacularly"\n- Pattern recognition: viewers love seeing hidden systems revealed',
  sources:
    "RAND Corporation, \"Iran's Political Economy since the Revolution\" (2024)\nCongressional Research Service, \"Iran Sanctions\" Report RL32048 (2023)\nIMF Working Paper WP/23/187, \"Sanctions and Economic Resilience\"\nBrookings Institution, \"The Iran-China Axis\" (2024)\nAtlantic Council, \"IRGC Inc.\" Economic Report (2023)\nUN Panel of Experts Report S/2023/171",
};

interface FieldDef {
  key: string;
  label: string;
  fullWidth: boolean;
  borderColor?: string;
  mono?: boolean;
}

const FIELDS: FieldDef[] = [
  { key: "thesis", label: "Thesis", fullWidth: true, borderColor: "var(--turquoise)" },
  { key: "executiveHook", label: "Executive Hook", fullWidth: true, borderColor: "var(--orange)" },
  { key: "factSheet", label: "Fact Sheet", fullWidth: false },
  { key: "historicalParallels", label: "Historical Parallels", fullWidth: false },
  { key: "frameworkAnalysis", label: "Framework Analysis", fullWidth: false },
  { key: "characterDossier", label: "Character Dossier", fullWidth: false },
  { key: "narrativeArc", label: "Narrative Arc", fullWidth: true },
  { key: "counterArguments", label: "Counter Arguments", fullWidth: false },
  { key: "visualSeeds", label: "Visual Seeds", fullWidth: false },
  { key: "themes", label: "Themes", fullWidth: false },
  { key: "psychologicalAngles", label: "Psychological Angles", fullWidth: false },
  { key: "sources", label: "Sources", fullWidth: true, mono: true },
];

interface ResearchTabProps {
  video: Video;
}

export function ResearchTab({ video }: ResearchTabProps) {
  return (
    <div className="space-y-4">
      {/* Headline */}
      <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--gold)" }}>
        <h3
          className="text-[10px] font-semibold uppercase tracking-wider mb-2"
          style={{ color: "var(--text-tertiary)" }}
        >
          Headline
        </h3>
        <p className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
          {MOCK_RESEARCH.headline}
        </p>
      </GlassCard>

      {/* Two-column research fields */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {FIELDS.map((field) => {
          const content = MOCK_RESEARCH[field.key];
          if (!content) return null;

          return (
            <GlassCard
              key={field.key}
              className={`p-5 ${field.fullWidth ? "lg:col-span-2" : ""}`}
              style={
                field.borderColor
                  ? { borderLeftWidth: 3, borderLeftColor: field.borderColor }
                  : undefined
              }
            >
              <h3
                className="text-[10px] font-semibold uppercase tracking-wider mb-3"
                style={{ color: "var(--text-tertiary)" }}
              >
                {field.label}
              </h3>
              <p
                className={`text-sm leading-relaxed whitespace-pre-line ${field.mono ? "font-mono text-xs" : ""}`}
                style={{ color: "var(--text-primary)" }}
              >
                {content}
              </p>
            </GlassCard>
          );
        })}
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 justify-end">
        <ActionButton variant="outline" icon={RefreshCw}>
          Re-research
        </ActionButton>
        <ActionButton variant="outline" icon={FileText}>
          Export to Google Docs
        </ActionButton>
      </div>
    </div>
  );
}
