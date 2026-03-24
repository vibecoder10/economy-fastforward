"use client";

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
}

interface CardHeaderProps {
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}

interface CardBodyProps {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--bg-card)] transition-colors hover:bg-[var(--bg-card-hover)]",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className, action }: CardHeaderProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between border-b border-[var(--border)] px-4 py-3",
        className
      )}
    >
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">{children}</h3>
      {action}
    </div>
  );
}

export function CardBody({ children, className }: CardBodyProps) {
  return (
    <div className={cn("p-[var(--card-padding)] text-[var(--text-secondary)]", className)}>
      {children}
    </div>
  );
}
