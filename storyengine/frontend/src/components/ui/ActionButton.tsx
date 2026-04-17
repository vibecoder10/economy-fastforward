"use client";

import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface ActionButtonProps {
  children: React.ReactNode;
  variant?: "filled" | "outline" | "warning";
  onClick?: () => void;
  disabled?: boolean;
  icon?: LucideIcon;
  className?: string;
}

export function ActionButton({
  children,
  variant = "filled",
  onClick,
  disabled,
  icon: Icon,
  className,
}: ActionButtonProps) {
  const styles = {
    filled: {
      background: "var(--turquoise)",
      color: "var(--bg-void)",
      border: "1px solid var(--turquoise)",
    },
    outline: {
      background: "transparent",
      color: "var(--orange)",
      border: "1px solid var(--orange)",
    },
    warning: {
      background: "transparent",
      color: "var(--red)",
      border: "1px solid var(--red)",
    },
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-disabled={disabled || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all active:scale-[0.98]",
        "enabled:hover:brightness-110",
        "disabled:opacity-40 disabled:grayscale disabled:cursor-not-allowed disabled:pointer-events-none",
        className
      )}
      style={styles[variant]}
    >
      {Icon && <Icon size={16} />}
      {children}
    </button>
  );
}
