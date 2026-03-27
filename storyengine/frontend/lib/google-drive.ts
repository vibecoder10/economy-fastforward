import { google } from "googleapis";
import { Readable } from "stream";

const DEFAULT_PARENT_FOLDER_ID = "1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD";

type UploadResult = {
  id: string;
  name: string;
  url: string;
};

export class GoogleDriveClient {
  private drive;
  private parentFolderId: string;

  constructor() {
    const clientId = process.env.GOOGLE_CLIENT_ID;
    const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
    const refreshToken = process.env.GOOGLE_REFRESH_TOKEN;

    if (!clientId || !clientSecret || !refreshToken) {
      throw new Error("Google OAuth credentials not found in environment");
    }

    this.parentFolderId =
      process.env.GOOGLE_DRIVE_FOLDER_ID || DEFAULT_PARENT_FOLDER_ID;

    const oauth2Client = new google.auth.OAuth2(clientId, clientSecret);
    oauth2Client.setCredentials({ refresh_token: refreshToken });

    this.drive = google.drive({ version: "v3", auth: oauth2Client });
  }

  getRootFolderId(): string {
    return this.parentFolderId;
  }

  async createFolder(
    name: string,
    parentId?: string
  ): Promise<{ id: string; name: string; url: string }> {
    const response = await this.drive.files.create({
      requestBody: {
        name,
        mimeType: "application/vnd.google-apps.folder",
        parents: [parentId || this.parentFolderId],
      },
      fields: "id, name",
    });

    const folderId = response.data.id!;
    return {
      id: folderId,
      name: response.data.name!,
      url: `https://drive.google.com/drive/folders/${folderId}`,
    };
  }

  async findFolderByName(
    name: string,
    parentId?: string
  ): Promise<{ id: string; name: string; url: string } | null> {
    const escapedName = name.replace(/'/g, "\\'");
    const query = [
      "mimeType = 'application/vnd.google-apps.folder'",
      `name = '${escapedName}'`,
      `'${parentId || this.parentFolderId}' in parents`,
      "trashed = false",
    ].join(" and ");

    const response = await this.drive.files.list({
      q: query,
      fields: "files(id, name)",
      pageSize: 1,
    });

    const match = response.data.files?.[0];
    if (!match?.id || !match.name) {
      return null;
    }

    return {
      id: match.id,
      name: match.name,
      url: `https://drive.google.com/drive/folders/${match.id}`,
    };
  }

  async getOrCreateFolder(
    name: string,
    parentId?: string
  ): Promise<{ id: string; name: string; url: string }> {
    const existing = await this.findFolderByName(name, parentId);
    if (existing) {
      return existing;
    }

    return this.createFolder(name, parentId);
  }

  async uploadFile(args: {
    content: Buffer;
    name: string;
    mimeType: string;
    folderId?: string;
  }): Promise<UploadResult> {
    const stream = new Readable();
    stream.push(args.content);
    stream.push(null);

    const response = await this.drive.files.create({
      requestBody: {
        name: args.name,
        parents: [args.folderId || this.parentFolderId],
      },
      media: {
        mimeType: args.mimeType,
        body: stream,
      },
      fields: "id, name",
    });

    const fileId = response.data.id!;

    await this.drive.permissions.create({
      fileId,
      requestBody: { role: "reader", type: "anyone" },
    });

    return {
      id: fileId,
      name: response.data.name!,
      url: `https://drive.google.com/uc?export=download&id=${fileId}`,
    };
  }

  async uploadAudio(
    content: Buffer,
    name: string,
    folderId?: string
  ): Promise<UploadResult> {
    return this.uploadFile({
      content,
      name,
      folderId,
      mimeType: "audio/mpeg",
    });
  }

  async uploadImage(
    content: Buffer,
    name: string,
    folderId?: string,
    mimeType = "image/png"
  ): Promise<UploadResult> {
    return this.uploadFile({
      content,
      name,
      folderId,
      mimeType,
    });
  }

  async uploadVideo(
    content: Buffer,
    name: string,
    folderId?: string
  ): Promise<UploadResult> {
    return this.uploadFile({
      content,
      name,
      folderId,
      mimeType: "video/mp4",
    });
  }

  async proxyFileToDrive(args: {
    sourceUrl: string;
    fileName: string;
    folderId?: string;
    mimeType: string;
  }): Promise<UploadResult> {
    const response = await fetch(args.sourceUrl);
    if (!response.ok) {
      throw new Error(`Failed to download remote file: ${response.status}`);
    }

    const content = Buffer.from(await response.arrayBuffer());
    return this.uploadFile({
      content,
      name: args.fileName,
      folderId: args.folderId,
      mimeType: args.mimeType,
    });
  }
}
