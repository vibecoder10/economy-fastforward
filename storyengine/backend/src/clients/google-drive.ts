/**
 * Google Drive Client for StoryEngine
 *
 * Ported from: skills/video-pipeline/clients/google_client.py
 * Handles file uploads, public sharing, and permanent URL generation.
 * CRITICAL: Never use temporary Kie.ai URLs — always proxy through Drive.
 */

import { google } from "googleapis";
import { Readable } from "stream";

export class GoogleDriveClient {
  private drive;
  private parentFolderId: string;

  constructor(
    clientId?: string,
    clientSecret?: string,
    refreshToken?: string,
    parentFolderId?: string
  ) {
    const cid = clientId || process.env.GOOGLE_CLIENT_ID;
    const secret = clientSecret || process.env.GOOGLE_CLIENT_SECRET;
    const token = refreshToken || process.env.GOOGLE_REFRESH_TOKEN;

    if (!cid || !secret || !token) {
      throw new Error("Google OAuth credentials not found in environment");
    }

    this.parentFolderId =
      parentFolderId ||
      process.env.GOOGLE_DRIVE_FOLDER_ID ||
      "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD";

    const oauth2Client = new google.auth.OAuth2(cid, secret);
    oauth2Client.setCredentials({ refresh_token: token });

    this.drive = google.drive({ version: "v3", auth: oauth2Client });
  }

  /**
   * Create a folder in Google Drive.
   */
  async createFolder(
    name: string,
    parentId?: string
  ): Promise<{ id: string; name: string }> {
    const res = await this.drive.files.create({
      requestBody: {
        name,
        mimeType: "application/vnd.google-apps.folder",
        parents: [parentId || this.parentFolderId],
      },
      fields: "id, name",
    });

    return { id: res.data.id!, name: res.data.name! };
  }

  /**
   * Upload an image to Google Drive and return its permanent URL.
   */
  async uploadImage(
    content: Buffer,
    name: string,
    folderId?: string
  ): Promise<{ id: string; name: string; url: string }> {
    const stream = new Readable();
    stream.push(content);
    stream.push(null);

    const res = await this.drive.files.create({
      requestBody: {
        name,
        parents: [folderId || this.parentFolderId],
      },
      media: {
        mimeType: "image/png",
        body: stream,
      },
      fields: "id, name",
    });

    const fileId = res.data.id!;

    // Make public
    await this.drive.permissions.create({
      fileId,
      requestBody: { role: "reader", type: "anyone" },
    });

    const url = `https://drive.google.com/uc?export=download&id=${fileId}`;
    return { id: fileId, name: res.data.name!, url };
  }

  /**
   * Download image from URL and upload to Drive.
   * Returns permanent Google Drive URL.
   */
  async proxyImageToDrive(
    imageUrl: string,
    fileName: string,
    folderId?: string
  ): Promise<string> {
    const res = await fetch(imageUrl);
    if (!res.ok) throw new Error(`Failed to download image: ${res.status}`);

    const buffer = Buffer.from(await res.arrayBuffer());
    const result = await this.uploadImage(
      buffer,
      fileName,
      folderId
    );

    return result.url;
  }

  /**
   * Convert a Drive view URL to a direct download URL.
   */
  static getDirectUrl(driveUrl: string): string | null {
    if (!driveUrl) return null;

    if (driveUrl.includes("export=download")) return driveUrl;

    const patterns = [
      /\/file\/d\/([a-zA-Z0-9_-]+)/,
      /[?&]id=([a-zA-Z0-9_-]+)/,
    ];

    for (const pattern of patterns) {
      const match = driveUrl.match(pattern);
      if (match) {
        return `https://drive.google.com/uc?export=download&id=${match[1]}`;
      }
    }

    return driveUrl;
  }
}
