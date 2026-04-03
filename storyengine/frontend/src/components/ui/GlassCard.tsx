"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
  id?: string;
}

export function GlassCard({ children, className, hover, onClick, style, id }: GlassCardProps) {
  const Component = hover ? motion.div : "div";
  const hoverProps = hover
    ? {
        whileHover: { scale: 1.02, borderColor: "rgba(0, 212, 170, 0.25)" },
        transition: { duration: 0.2 },
      }
    : {};

  return (
    <Component
      id={id}
      className={cn("glass-card p-6", className)}
      onClick={onClick}
      style={{ cursor: onClick ? "pointer" : undefined, ...style }}
      {...hoverProps}
    >
      {children}
    </Component>
  );
}
