"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPendingReview, approveAsset, rejectAsset, advanceVideo, approveStoryboard, rejectStoryboard, type ReviewItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/EmptyState";
import { FileText, Image, Palette, LayoutGrid, ChevronRight, Check, X } from "lucide-react";

type ReviewTab = "scripts" | "storyboards" | "thumbnails" | "images";

export default function ReviewPage() {
  const [activeTab, setActiveTab] = useState<ReviewTab>("scripts");
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [imageReviewIndex, setImageReviewIndex] = useState(0);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["pending-review"],
    queryFn: getPendingReview,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const advanceMutation = useMutation({
    mutationFn: (id: string) => advanceVideo(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const approveStoryboardMutation = useMutation({
    mutationFn: (scriptId: string) => { setPendingId(scriptId); return approveStoryboard(scriptId); },
    onSettled: () => { setPendingId(null); queryClient.invalidateQueries({ queryKey: ["pending-review"] }); },
  });

  const rejectStoryboardMutation = useMutation({
    mutationFn: (scriptId: string) => { setPendingId(scriptId); return rejectStoryboard(scriptId); },
    onSettled: () => { setPendingId(null); queryClient.invalidateQueries({ queryKey: ["pending-review"] }); },
  });

  const tabs: { key: ReviewTab; label: string; icon: typeof FileText; count: number }[] = [
    { key: "scripts", label: "Scripts", icon: FileText, count: data?.scripts.length ?? 0 },
    { key: "storyboards", label: "Storyboards", icon: LayoutGrid, count: data?.storyboards.length ?? 0 },
    { key: "thumbnails", label: "Thumbnails", icon: Palette, count: data?.thumbnails.length ?? 0 },
    { key: "images", label: "Images", icon: Image, count: data?.images.length ?? 0 },
  ];

  const totalPending = tabs.reduce((sum, t) => sum + t.count, 0);
  const currentItems = data?.[activeTab] ?? [];

  // Image batch review mode
  const imageItems = data?.images ?? [];
  const currentImage = imageItems[imageReviewIndex];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Review</h1>
        {totalPending > 0 && (
          <span className="rounded-full bg-[var(--accent)]/20 px-2.5 py-1 text-xs font-medium text-[var(--accent)]">
            {totalPending} pending
          </span>
        )}
      </div>

      {/* Tab selector */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setSelectedItem(null);
                setImageReviewIndex(0);
              }}
              className={cn(
                "flex flex-shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                activeTab === tab.key
                  ? "bg-[var(--accent)] text-black"
                  : "bg-[var(--surface)] text-[var(--text-secondary)]"
              )}
            >
              <Icon size={14} />
              {tab.label}
              {tab.count > 0 && (
                <span className={cn(
                  "ml-0.5 rounded-full px-1.5 py-0.5 text-[10px]",
                  activeTab === tab.key ? "bg-black/20" : "bg-white/10"
                )}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-[var(--surface)]" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && currentItems.length === 0 && (
        <EmptyState
          icon={activeTab === "scripts" ? FileText : activeTab === "storyboards" ? LayoutGrid : activeTab === "thumbnails" ? Palette : Image}
          title={`No ${activeTab} pending review`}
          description="Items appear here when pipeline stages complete"
        />
      )}

      {/* Scripts */}
      {activeTab === "scripts" && !selectedItem && (
        <div className="space-y-2">
          {currentItems.map((item) => (
            <button
              key={item.video_id}
              onClick={() => setSelectedItem(item)}
              className="flex w-full items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left transition-colors hover:bg-[var(--surface-elevated)]"
            >
              <div>
                <p className="font-medium">{item.title}</p>
                <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                  {item.word_count?.toLocaleString()} words
                </p>
              </div>
              <ChevronRight size={16} className="text-[var(--text-secondary)]" />
            </button>
          ))}
        </div>
      )}

      {/* Script reader */}
      {activeTab === "scripts" && selectedItem && (
        <div className="space-y-4">
          <button
            onClick={() => setSelectedItem(null)}
            className="text-xs text-[var(--accent)]"
          >
            ← Back to list
          </button>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h2 className="mb-4 text-lg font-semibold">{selectedItem.title}</h2>
            <div className="prose prose-invert max-w-none text-[16px] leading-[1.6] text-[var(--text-primary)]">
              <p className="whitespace-pre-wrap">Script content will load from API...</p>
            </div>
          </div>
          <div className="sticky bottom-16 z-10 flex gap-2 rounded-xl bg-[var(--surface)] p-3 md:bottom-0">
            <button
              onClick={() => {
                advanceMutation.mutate(selectedItem.video_id);
                setSelectedItem(null);
              }}
              className="flex-1 rounded-lg bg-[var(--accent)] py-3 text-sm font-medium text-black"
            >
              Approve Script
            </button>
            <button
              onClick={() => setSelectedItem(null)}
              className="rounded-lg border border-[var(--border)] px-4 py-3 text-sm font-medium text-[var(--text-secondary)]"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {/* Storyboards */}
      {activeTab === "storyboards" && (
        <div className="space-y-4">
          {currentItems.map((item) => (
            <div
              key={item.script_id || item.video_id}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <p className="mb-3 font-medium">{item.title || "Untitled"}</p>
              <p className="mb-2 text-xs text-[var(--text-secondary)]">Scene {item.scene}</p>
              <div className="grid grid-cols-3 gap-2">
                {item.storyboard_1_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_1_url} alt="Grid 1" className="w-full" />
                  </div>
                )}
                {item.storyboard_2_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_2_url} alt="Grid 2" className="w-full" />
                  </div>
                )}
                {item.storyboard_3_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_3_url} alt="Grid 3" className="w-full" />
                  </div>
                )}
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => item.script_id && approveStoryboardMutation.mutate(item.script_id)}
                  disabled={pendingId === item.script_id}
                  className="flex-1 rounded-lg bg-[var(--success)]/20 py-2 text-sm font-medium text-[var(--success)] disabled:opacity-50"
                >
                  {pendingId === item.script_id && approveStoryboardMutation.isPending ? "Approving..." : "Approve"}
                </button>
                <button
                  onClick={() => item.script_id && rejectStoryboardMutation.mutate(item.script_id)}
                  disabled={pendingId === item.script_id}
                  className="flex-1 rounded-lg bg-[var(--error)]/20 py-2 text-sm font-medium text-[var(--error)] disabled:opacity-50"
                >
                  {pendingId === item.script_id && rejectStoryboardMutation.isPending ? "Rejecting..." : "Reject"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Thumbnails */}
      {activeTab === "thumbnails" && (
        <div className="space-y-4">
          {/* Group by video */}
          {currentItems.map((item) => (
            <div
              key={item.asset_id}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <p className="mb-3 text-sm font-medium">{item.title}</p>
              <div className="grid grid-cols-2 gap-2">
                {item.url && (
                  <button
                    onClick={() => item.asset_id && approveMutation.mutate(item.asset_id)}
                    className="group relative overflow-hidden rounded-lg"
                  >
                    <img src={item.url} alt="" className="aspect-video w-full object-cover" />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/40">
                      <Check size={24} className="text-white opacity-0 transition-opacity group-hover:opacity-100" />
                    </div>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Images batch review */}
      {activeTab === "images" && imageItems.length > 0 && (
        <div className="space-y-4">
          {/* Progress */}
          <div className="flex items-center justify-between text-sm text-[var(--text-secondary)]">
            <span>Image {imageReviewIndex + 1} of {imageItems.length}</span>
            <div className="h-1 flex-1 mx-3 rounded-full bg-white/5">
              <div
                className="h-1 rounded-full bg-[var(--accent)] transition-all"
                style={{ width: `${((imageReviewIndex + 1) / imageItems.length) * 100}%` }}
              />
            </div>
          </div>

          {/* Current image */}
          {currentImage && (
            <div className="overflow-hidden rounded-xl">
              {currentImage.url && (
                <img src={currentImage.url} alt="" className="aspect-video w-full object-cover" />
              )}
              {currentImage.prompt && (
                <p className="mt-2 text-xs text-[var(--text-secondary)]">{currentImage.prompt}</p>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                if (currentImage?.asset_id) rejectMutation.mutate(currentImage.asset_id);
                setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1));
              }}
              className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--error)]/20 text-sm font-medium text-[var(--error)]"
            >
              <X size={16} /> Reject
            </button>
            <button
              onClick={() => setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1))}
              className="flex min-h-[44px] items-center justify-center rounded-lg border border-[var(--border)] px-4 text-sm text-[var(--text-secondary)]"
            >
              Skip
            </button>
            <button
              onClick={() => {
                if (currentImage?.asset_id) approveMutation.mutate(currentImage.asset_id);
                setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1));
              }}
              className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--success)]/20 text-sm font-medium text-[var(--success)]"
            >
              <Check size={16} /> Approve
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
