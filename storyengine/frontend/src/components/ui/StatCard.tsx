"use client";

import { motion } from "framer-motion";
import { TrendingUp, TrendingDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  detail?: string;
  color: string;
  icon?: LucideIcon;
  trend?: "up" | "down";
  ringValue?: number;
}

export function StatCard({ label, value, detail, color, icon: Icon, trend, ringValue }: StatCardProps) {
  const radius = 20;
  const circumference = 2 * Math.PI * radius;
  const offset = ringValue !== undefined ? circumference * (1 - ringValue / 100) : 0;

  return (
    <motion.div
      className="glass-card p-5 relative overflow-hidden"
      style={{ borderColor: `${color}33` }}
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.2 }}
    >
      {/* Top color accent line */}
      <div
        className="absolute top-0 left-0 right-0 h-0.5"
        style={{ background: color }}
      />

      <div className="flex items-start justify-between">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider mb-1" style={{ color }}>
            {label}
          </p>
          <p className="text-2xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            {value}
          </p>
          {detail && (
            <p className="text-[11px] mt-1 font-mono" style={{ color: "var(--text-secondary)" }}>
              {detail}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {trend && (
            <span style={{ color: trend === "up" ? "var(--green)" : "var(--red)" }}>
              {trend === "up" ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
            </span>
          )}
          {ringValue !== undefined && (
            <svg width="52" height="52" className="-rotate-90">
              <circle cx="26" cy="26" r={radius} fill="none" stroke="var(--bg-elevated)" strokeWidth="4" />
              <motion.circle
                cx="26"
                cy="26"
                r={radius}
                fill="none"
                stroke={color}
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray={circumference}
                initial={{ strokeDashoffset: circumference }}
                animate={{ strokeDashoffset: offset }}
                transition={{ duration: 1.2, ease: "easeOut" as const }}
              />
            </svg>
          )}
          {Icon && !ringValue && (
            <Icon size={18} style={{ color, opacity: 0.6 }} />
          )}
        </div>
      </div>
    </motion.div>
  );
}
