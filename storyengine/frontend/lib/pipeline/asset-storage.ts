import { GoogleDriveClient } from "@/lib/google-drive";
import type { VideoRow } from "./types";
import { updateVideoDriveFolder } from "./write-store";

type AssetFolderKind =
  | "audio"
  | "images"
  | "video"
  | "thumbnails"
  | "storyboards"
  | "sound";

const FOLDER_NAMES: Record<AssetFolderKind, string> = {
  audio: "audio",
  images: "images",
  video: "video",
  thumbnails: "thumbnails",
  storyboards: "storyboards",
  sound: "sound",
};

function safeVideoFolderName(video: VideoRow): string {
  const raw =
    typeof video.video_title === "string" && video.video_title.trim()
      ? video.video_title.trim()
      : `video-${String(video.id ?? "untitled")}`;

  return raw.replace(/[<>:"/\\|?*\u0000-\u001F]/g, "").slice(0, 120);
}

export async function ensureVideoDriveFolder(video: VideoRow): Promise<{
  driveFolderId: string;
  driveFolderLink: string;
}> {
  const existingId =
    typeof video.drive_folder_id === "string" ? video.drive_folder_id : "";
  const existingLink =
    typeof video.drive_folder_link === "string" ? video.drive_folder_link : "";

  if (existingId && existingLink) {
    return {
      driveFolderId: existingId,
      driveFolderLink: existingLink,
    };
  }

  const drive = new GoogleDriveClient();
  const folder = await drive.getOrCreateFolder(safeVideoFolderName(video));

  if (video.id) {
    await updateVideoDriveFolder({
      videoId: video.id,
      driveFolderId: folder.id,
      driveFolderLink: folder.url,
    });
  }

  return {
    driveFolderId: folder.id,
    driveFolderLink: folder.url,
  };
}

export async function ensureVideoAssetSubfolder(args: {
  video: VideoRow;
  kind: AssetFolderKind;
}): Promise<{ folderId: string; folderLink: string }> {
  const drive = new GoogleDriveClient();
  const { driveFolderId } = await ensureVideoDriveFolder(args.video);
  const subfolder = await drive.getOrCreateFolder(
    FOLDER_NAMES[args.kind],
    driveFolderId
  );

  return {
    folderId: subfolder.id,
    folderLink: subfolder.url,
  };
}

export async function uploadGeneratedAudio(args: {
  video: VideoRow;
  fileName: string;
  content: Buffer;
}): Promise<{ fileId: string; url: string }> {
  const drive = new GoogleDriveClient();
  const { folderId } = await ensureVideoAssetSubfolder({
    video: args.video,
    kind: "audio",
  });
  const result = await drive.uploadAudio(args.content, args.fileName, folderId);
  return { fileId: result.id, url: result.url };
}

export async function proxyGeneratedImage(args: {
  video: VideoRow;
  fileName: string;
  sourceUrl: string;
  mimeType?: string;
}): Promise<{ fileId: string; url: string }> {
  const drive = new GoogleDriveClient();
  const { folderId } = await ensureVideoAssetSubfolder({
    video: args.video,
    kind: "images",
  });
  const result = await drive.proxyFileToDrive({
    sourceUrl: args.sourceUrl,
    fileName: args.fileName,
    folderId,
    mimeType: args.mimeType ?? "image/png",
  });
  return { fileId: result.id, url: result.url };
}

export async function proxyGeneratedVideo(args: {
  video: VideoRow;
  fileName: string;
  sourceUrl: string;
  mimeType?: string;
}): Promise<{ fileId: string; url: string }> {
  const drive = new GoogleDriveClient();
  const { folderId } = await ensureVideoAssetSubfolder({
    video: args.video,
    kind: "video",
  });
  const result = await drive.proxyFileToDrive({
    sourceUrl: args.sourceUrl,
    fileName: args.fileName,
    folderId,
    mimeType: args.mimeType ?? "video/mp4",
  });
  return { fileId: result.id, url: result.url };
}

export async function proxyGeneratedSound(args: {
  video: VideoRow;
  fileName: string;
  sourceUrl: string;
  mimeType?: string;
}): Promise<{ fileId: string; url: string }> {
  const drive = new GoogleDriveClient();
  const { folderId } = await ensureVideoAssetSubfolder({
    video: args.video,
    kind: "sound",
  });
  const result = await drive.proxyFileToDrive({
    sourceUrl: args.sourceUrl,
    fileName: args.fileName,
    folderId,
    mimeType: args.mimeType ?? "audio/mpeg",
  });
  return { fileId: result.id, url: result.url };
}
