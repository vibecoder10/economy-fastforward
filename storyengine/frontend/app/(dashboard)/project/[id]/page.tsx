"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

type AssetRow = {
  id?: string | number;
  scene?: number;
  sentence_index?: number;
  sentence_text?: string;
  image_index?: number;
  image_prompt?: string;
  video_prompt?: string;
  shot_type?: string;
  status?: string;
  image_url?: string;
  drive_image_url?: string;
  video_clip_url?: string;
};

type Scene = {
  id: string;
  sceneNumber: number;
  sceneText: string;
  scriptStatus: string;
  voiceStatus: string;
  voiceOverUrl?: string;
  assets: AssetRow[];
};

type VideoDetail = {
  video: {
    id?: string | number;
    video_title?: string;
    status?: string;
  };
  scenes: Scene[];
  transitions: Array<{
    id?: string | number;
    from_status?: string;
    to_status?: string;
    triggered_by?: string;
    error_message?: string;
    created_at?: string;
  }>;
};

function formatStatus(status?: string) {
  return (status || "unknown").replaceAll("_", " ");
}

export default function ProjectPage() {
  const params = useParams();
  const videoId = params.id as string;

  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busyScene, setBusyScene] = useState<number | null>(null);
  const [busyVoiceScene, setBusyVoiceScene] = useState<number | null>(null);
  const [busyAssetId, setBusyAssetId] = useState<string | null>(null);
  const [busyClipAssetId, setBusyClipAssetId] = useState<string | null>(null);

  async function loadDetail() {
    try {
      const res = await fetch(`/api/videos/${videoId}`);
      if (!res.ok) throw new Error("Failed to load video");
      const data = await res.json();
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load video");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDetail();
  }, [videoId]);

  async function handleGenerateImagePrompts(sceneNumber: number) {
    setBusyScene(sceneNumber);
    setMessage("");

    try {
      const res = await fetch(`/api/videos/${videoId}/image-prompts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sceneNumber }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to generate image prompts");
      }

      setMessage(
        data.asset_insert_error
          ? `Prompts generated for Scene ${sceneNumber}, but saving prompt assets failed: ${data.asset_insert_error}`
          : `Prompts generated and inserted for Scene ${sceneNumber}.`
      );

      await loadDetail();
    } catch (err) {
      setMessage(
        err instanceof Error ? err.message : "Failed to generate image prompts"
      );
    } finally {
      setBusyScene(null);
    }
  }

  async function handleGenerateVoice(sceneNumber: number) {
    setBusyVoiceScene(sceneNumber);
    setMessage("");

    try {
      const res = await fetch(`/api/videos/${videoId}/voice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sceneNumber }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to generate voice");
      }

      if (data.skipped) {
        setMessage(`Scene ${sceneNumber}: ${data.reason}.`);
      } else {
        setMessage(
          data.script_update_error
            ? `Voice generated for Scene ${sceneNumber}, but saving the script row failed: ${data.script_update_error}`
            : `Voice generated and saved for Scene ${sceneNumber}.`
        );
      }

      await loadDetail();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to generate voice");
    } finally {
      setBusyVoiceScene(null);
    }
  }

  async function handleGenerateImage(assetId: string) {
    setBusyAssetId(assetId);
    setMessage("");

    try {
      const res = await fetch(`/api/videos/${videoId}/images`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assetId }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to generate image");
      }

      if (data.skipped) {
        setMessage(`Image skipped: ${data.reason}.`);
      } else {
        setMessage(
          data.asset_update_error
            ? `Image generated, but saving the asset row failed: ${data.asset_update_error}`
            : "Image generated and saved."
        );
      }

      await loadDetail();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to generate image");
    } finally {
      setBusyAssetId(null);
    }
  }

  async function handleGenerateClip(assetId: string) {
    setBusyClipAssetId(assetId);
    setMessage("");

    try {
      const res = await fetch(`/api/videos/${videoId}/clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assetId }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to generate clip");
      }

      if (data.skipped) {
        setMessage(`Clip skipped: ${data.reason}.`);
      } else {
        setMessage(
          data.asset_update_error
            ? `Clip generated, but saving the asset row failed: ${data.asset_update_error}`
            : "Clip generated and saved."
        );
      }

      await loadDetail();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to generate clip");
    } finally {
      setBusyClipAssetId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="text-text-secondary">Loading video...</div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="text-error">{error || "Video not found"}</div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold mb-1">{detail.video.video_title || "Untitled video"}</h1>
        <p className="text-text-secondary text-sm">
          Status: <span className="capitalize">{formatStatus(detail.video.status)}</span>
        </p>
        {message && <p className="text-sm text-text-secondary mt-3">{message}</p>}
      </div>

      <section className="space-y-6">
        {detail.scenes.length === 0 ? (
          <div className="border border-border border-dashed rounded-xl p-12 text-center">
            <h3 className="text-lg font-medium text-text-primary mb-2">No script scenes found</h3>
            <p className="text-text-secondary">
              This video does not currently have any rows in `scripts` that the UI can load.
            </p>
          </div>
        ) : (
          detail.scenes.map((scene) => {
            const promptAssets = scene.assets.filter(
              (asset) => !!asset.image_prompt
            );

            return (
              <div
                key={scene.id}
                className="border border-border rounded-xl overflow-hidden"
              >
                <div className="bg-surface px-5 py-4 border-b border-border flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold">Scene {scene.sceneNumber}</h3>
                    <p className="text-sm text-text-secondary mt-0.5">
                      Script: {formatStatus(scene.scriptStatus)} | Voice:{" "}
                      {formatStatus(scene.voiceStatus)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => handleGenerateImagePrompts(scene.sceneNumber)}
                      disabled={busyScene === scene.sceneNumber}
                      className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background text-sm font-medium rounded-lg transition-colors"
                    >
                      {busyScene === scene.sceneNumber
                        ? "Generating..."
                        : "Generate Image Prompts"}
                    </button>
                    <button
                      onClick={() => handleGenerateVoice(scene.sceneNumber)}
                      disabled={busyVoiceScene === scene.sceneNumber || !!scene.voiceOverUrl}
                      className="px-4 py-2 border border-border hover:bg-surface disabled:opacity-50 text-text-primary text-sm font-medium rounded-lg transition-colors"
                    >
                      {busyVoiceScene === scene.sceneNumber
                        ? "Generating Voice..."
                        : scene.voiceOverUrl
                          ? "Voice Ready"
                          : "Generate Voice"}
                    </button>
                  </div>
                </div>

                <div className="p-5 space-y-5">
                  <div>
                    <h4 className="text-xs font-medium text-text-tertiary uppercase tracking-wide mb-2">
                      Scene Text
                    </h4>
                    <p className="text-sm text-text-secondary leading-relaxed">
                      {scene.sceneText || "No scene text available"}
                    </p>
                  </div>

                  {scene.voiceOverUrl && (
                    <div>
                      <h4 className="text-xs font-medium text-text-tertiary uppercase tracking-wide mb-2">
                        Voice Over
                      </h4>
                      <a
                        href={scene.voiceOverUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm text-accent hover:underline"
                      >
                        Open voice-over asset
                      </a>
                    </div>
                  )}

                  {promptAssets.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="text-xs font-medium text-text-tertiary uppercase tracking-wide">
                        Prompt Assets ({promptAssets.length})
                      </h4>
                      {promptAssets.map((asset, index) => (
                        <div
                          key={`${asset.id ?? "prompt"}-${index}`}
                          className="grid grid-cols-12 gap-4 p-4 bg-surface rounded-lg border border-border"
                        >
                          <div className="col-span-4">
                            <div className="text-xs font-medium text-text-tertiary mb-1">
                              Script Segment
                            </div>
                            <p className="text-sm text-text-primary leading-relaxed">
                              {asset.sentence_text || "No segment metadata"}
                            </p>
                          </div>

                          <div className="col-span-5">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-medium text-text-tertiary">
                                Prompt
                              </span>
                              <span className="px-2 py-0.5 bg-accent/20 text-accent text-xs font-medium rounded">
                                {asset.shot_type || "unknown"}
                              </span>
                            </div>
                            <p className="text-sm text-text-secondary leading-relaxed line-clamp-5">
                              {asset.image_prompt || "No prompt text available"}
                            </p>
                          </div>

                          <div className="col-span-3">
                            {asset.image_url || asset.drive_image_url || asset.video_clip_url ? (
                              <div className="space-y-2">
                                {(asset.image_url || asset.drive_image_url) && (
                                  <a
                                    href={asset.image_url || asset.drive_image_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-sm text-accent hover:underline block"
                                  >
                                    Open image
                                  </a>
                                )}
                                {asset.video_clip_url && (
                                  <a
                                    href={asset.video_clip_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-sm text-accent hover:underline block"
                                  >
                                    Open clip
                                  </a>
                                )}
                                <div className="text-xs text-text-tertiary">
                                  Status: {formatStatus(asset.status)}
                                </div>
                                {(asset.image_url || asset.drive_image_url) &&
                                  !asset.video_clip_url &&
                                  asset.id && (
                                    <button
                                      onClick={() => handleGenerateClip(String(asset.id))}
                                      disabled={
                                        busyClipAssetId === String(asset.id) ||
                                        !!asset.video_clip_url
                                      }
                                      className="px-3 py-1.5 border border-border hover:bg-surface disabled:opacity-50 text-text-primary text-xs font-medium rounded-lg transition-colors"
                                    >
                                      {busyClipAssetId === String(asset.id)
                                        ? "Generating Clip..."
                                        : asset.video_clip_url
                                          ? "Clip Ready"
                                          : "Generate Clip"}
                                    </button>
                                  )}
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <div className="text-xs text-text-tertiary">
                                  Status: {formatStatus(asset.status)}
                                </div>
                                {asset.id && (
                                  <button
                                    onClick={() => handleGenerateImage(String(asset.id))}
                                    disabled={
                                      busyAssetId === String(asset.id) ||
                                      !!asset.image_url ||
                                      !!asset.drive_image_url
                                    }
                                    className="px-3 py-1.5 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background text-xs font-medium rounded-lg transition-colors"
                                  >
                                    {busyAssetId === String(asset.id)
                                      ? "Generating..."
                                      : asset.image_url || asset.drive_image_url
                                        ? "Image Ready"
                                        : "Generate Image"}
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>

      <section className="border border-border rounded-xl p-5">
        <h3 className="font-semibold mb-4">Stage Log</h3>
        {detail.transitions.length === 0 ? (
          <p className="text-sm text-text-secondary">
            No stage transitions logged yet.
          </p>
        ) : (
          <div className="space-y-3">
            {detail.transitions.slice(0, 12).map((transition, index) => (
              <div
                key={`${transition.id ?? "transition"}-${index}`}
                className="text-sm text-text-secondary border-b border-border last:border-b-0 pb-3 last:pb-0"
              >
                <div className="text-text-primary">
                  {formatStatus(transition.from_status)} {"->"} {formatStatus(transition.to_status)}
                </div>
                <div>{transition.error_message || "Transition logged"}</div>
                <div className="text-xs text-text-tertiary mt-1">
                  {transition.triggered_by || "unknown source"}
                  {transition.created_at ? ` • ${new Date(transition.created_at).toLocaleString()}` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
