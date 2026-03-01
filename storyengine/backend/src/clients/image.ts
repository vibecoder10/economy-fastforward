/**
 * Image Generation Client via Kie.ai API
 *
 * Ported from: skills/video-pipeline/clients/image_client.py
 * Supports Nano Banana 2 (scene images) and Nano Banana Pro (thumbnails).
 */

const CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask";
const RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo";

// Model routing
const SCENE_MODEL = "nano-banana-2";
const THUMBNAIL_MODEL = "nano-banana-pro";

export class ImageClient {
  private apiKey: string;

  constructor(apiKey?: string) {
    const key = apiKey || process.env.KIE_AI_API_KEY;
    if (!key) {
      throw new Error("KIE_AI_API_KEY not found");
    }
    this.apiKey = key;
  }

  private get headers() {
    return {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
    };
  }

  /**
   * Create an image generation task.
   */
  async createImage(
    prompt: string,
    aspectRatio: string = "16:9",
    model?: string
  ): Promise<{ taskId: string } | null> {
    const useModel = model || THUMBNAIL_MODEL;

    // nano-banana-pro uses aspect_ratio; others use image_size
    const sizeParam =
      useModel === THUMBNAIL_MODEL
        ? { aspect_ratio: aspectRatio }
        : { image_size: aspectRatio };

    const payload = {
      model: useModel,
      input: {
        prompt,
        ...sizeParam,
        output_format: "png",
      },
    };

    const res = await fetch(CREATE_TASK_URL, {
      method: "POST",
      headers: this.headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      console.error(`Image API error: ${res.status} - ${await res.text()}`);
      return null;
    }

    const data = await res.json();
    const taskId = data?.data?.taskId;
    return taskId ? { taskId } : null;
  }

  /**
   * Poll for task completion.
   */
  async pollForCompletion(
    taskId: string,
    maxAttempts: number = 45,
    pollInterval: number = 2000
  ): Promise<string[] | null> {
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const res = await fetch(
          `${RECORD_INFO_URL}?taskId=${taskId}`,
          { headers: { Authorization: `Bearer ${this.apiKey}` } }
        );
        const status = await res.json();
        const data = status?.data;

        // Status: 0=Queue, 1=Running, 2=Success, 3=Failed
        if (data?.status === 3) return null;

        const resultJson = data?.resultJson;
        if (resultJson) {
          const result =
            typeof resultJson === "string"
              ? JSON.parse(resultJson)
              : resultJson;
          const urls = result?.resultUrls;
          if (urls?.length) return urls;
        }
      } catch (e) {
        console.error("Poll error:", e);
      }

      await new Promise((r) => setTimeout(r, pollInterval));
    }

    return null;
  }

  /**
   * Generate a scene image using Nano Banana 2 with reference.
   */
  async generateSceneImage(
    prompt: string,
    referenceImageUrl: string,
    seed?: number
  ): Promise<{ url: string; seed?: number } | null> {
    const payload: Record<string, unknown> = {
      model: SCENE_MODEL,
      input: {
        prompt,
        image_input: [referenceImageUrl],
        aspect_ratio: "16:9",
        resolution: "1K",
        output_format: "png",
      },
    };

    try {
      const res = await fetch(CREATE_TASK_URL, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        console.error(`Scene image API error: ${res.status}`);
        return null;
      }

      const taskData = await res.json();
      const taskId = taskData?.data?.taskId;
      if (!taskId) return null;

      await new Promise((r) => setTimeout(r, 5000));
      const urls = await this.pollForCompletion(taskId, 60);

      if (urls?.length) {
        return {
          url: urls[0],
          seed: undefined,
        };
      }
      return null;
    } catch (e) {
      console.error("Scene image error:", e);
      return null;
    }
  }

  /**
   * Generate a thumbnail using Nano Banana Pro.
   */
  async generateThumbnail(prompt: string): Promise<string[] | null> {
    const result = await this.createImage(prompt, "16:9", THUMBNAIL_MODEL);
    if (!result) return null;

    await new Promise((r) => setTimeout(r, 5000));
    return this.pollForCompletion(result.taskId);
  }

  /**
   * Generate a video from an image using Grok Imagine.
   */
  async generateVideo(
    imageUrl: string,
    prompt: string,
    duration: number = 6
  ): Promise<string | null> {
    const durationStr = duration === 10 ? "10" : "6";

    const payload = {
      model: "grok-imagine/image-to-video",
      input: {
        image_urls: [imageUrl],
        prompt,
        duration: durationStr,
        mode: "normal",
      },
    };

    const maxRetries = 3;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const res = await fetch(CREATE_TASK_URL, {
          method: "POST",
          headers: this.headers,
          body: JSON.stringify(payload),
        });

        if (!res.ok) continue;

        const taskData = await res.json();
        const taskId = taskData?.data?.taskId;
        if (!taskId) continue;

        await new Promise((r) => setTimeout(r, 10000));
        const urls = await this.pollForCompletion(taskId, 120, 5000);

        if (urls?.length) return urls[0];
      } catch (e) {
        console.error(`Video generation error (attempt ${attempt + 1}):`, e);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }

    return null;
  }
}
