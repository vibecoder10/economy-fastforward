"use client";

import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeClasses = {
  sm: 14,
  md: 20,
  lg: 28,
};

export function Spinner({ size = "md", className }: SpinnerProps) {
  return (
    <Loader2
      size={sizeClasses[size]}
      className={cn("animate-spin text-[var(--accent)]", className)}
    />
  );
}
