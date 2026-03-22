"use client";

import { useEffect, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DetailPanelProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

export function DetailPanel({ open, onClose, title, children }: DetailPanelProps) {
  // Prevent body scroll when open on mobile
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60"
            onClick={onClose}
          />

          {/* Mobile: Bottom sheet */}
          <motion.div
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed inset-x-0 bottom-0 z-50 max-h-[80vh] overflow-y-auto rounded-t-2xl bg-[var(--surface)] md:hidden"
          >
            {/* Drag handle */}
            <div className="sticky top-0 z-10 flex items-center justify-center bg-[var(--surface)] pb-2 pt-3">
              <div className="h-1 w-8 rounded-full bg-white/20" />
            </div>
            {title && (
              <div className="flex items-center justify-between border-b border-[var(--border)] px-4 pb-3">
                <h2 className="text-lg font-semibold">{title}</h2>
                <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-white/10">
                  <X size={18} />
                </button>
              </div>
            )}
            <div className="px-4 pb-6 pt-3">{children}</div>
          </motion.div>

          {/* Desktop: Side panel */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed right-0 top-0 z-50 hidden h-screen w-[480px] overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] md:block"
          >
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-5 py-4">
              <h2 className="text-lg font-semibold">{title}</h2>
              <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-white/10">
                <X size={18} />
              </button>
            </div>
            <div className="p-5">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
