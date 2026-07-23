"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { getDriveStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export function DriveStorageNotice({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["driveStatus"],
    queryFn: getDriveStatus,
    staleTime: 60_000,
  });

  if (isLoading || data?.connected) return null;

  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2.5 rounded-xl",
        compact ? "px-3 py-2.5" : "px-4 py-3",
        className,
      )}
      style={{
        background: "rgba(245,158,11,0.08)",
        border: "1px solid rgba(245,158,11,0.28)",
      }}
    >
      <HardDrive
        size={compact ? 14 : 16}
        className="shrink-0 mt-0.5"
        style={{ color: "var(--gold)" }}
      />
      <p
        className={compact ? "text-[10px] leading-relaxed" : "text-xs leading-relaxed"}
        style={{ color: "var(--text-secondary)" }}
      >
        <strong style={{ color: "var(--text-primary)" }}>
          Your media is currently stored on StoryEngine.
        </strong>{" "}
        StoryEngine storage isn&apos;t guaranteed long-term.{" "}
        <Link
          href="/settings#google-drive-storage"
          className="font-semibold underline underline-offset-2"
          style={{ color: "var(--gold)" }}
        >
          Connect Google Drive to own and keep your files.
        </Link>
      </p>
    </div>
  );
}
