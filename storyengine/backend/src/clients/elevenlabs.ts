/**
 * ElevenLabs Voice Synthesis Client for StoryEngine
 *
 * Ported from: skills/video-pipeline/clients/elevenlabs_client.py
 * Uses Wavespeed API endpoint for ElevenLabs turbo.
 */

const WAVESPEED_API_URL =
  "https://api.wavespeed.ai/api/v3/elevenlabs/turbo-v2.5";
const DEFAULT_VOICE_ID = "G17SuINrv2H9FC6nvetn";

export class ElevenLabsClient {
  private apiKey: string;
  private voiceId: string;

  constructor(apiKey?: string, voiceId?: string) {
    const key = apiKey || process.env.WAVESPEED_API_KEY;
    if (!key) {
      throw new Error("WAVESPEED_API_KEY not found");
    }
    this.apiKey = key;
    this.voiceId = voiceId || process.env.ELEVENLABS_VOICE_ID || DEFAULT_VOICE_ID;
  }

  async generateVoice(
    text: string,
    voiceId?: string
  ): Promise<{ getUrl: string } | null> {
    const res = await fetch(WAVESPEED_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        voice_id: voiceId || this.voiceId,
        similarity: "1.0",
        stability: "0.5",
        use_speaker_boost: true,
      }),
    });

    if (!res.ok) return null;
    const data = await res.json();
    const getUrl = data?.data?.urls?.get;
    return getUrl ? { getUrl } : null;
  }

  async pollForCompletion(
    getUrl: string,
    maxAttempts: number = 30,
    pollInterval: number = 5000
  ): Promise<string | null> {
    for (let i = 0; i < maxAttempts; i++) {
      const res = await fetch(getUrl, {
        headers: { Authorization: `Bearer ${this.apiKey}` },
      });

      if (!res.ok) continue;

      const data = await res.json();
      const status = data?.data?.status;

      if (status === "completed") {
        const outputs = data?.data?.outputs;
        return outputs?.[0] || null;
      }
      if (status === "failed") return null;

      await new Promise((r) => setTimeout(r, pollInterval));
    }

    return null;
  }

  async generateAndWait(
    text: string,
    voiceId?: string
  ): Promise<string | null> {
    const result = await this.generateVoice(text, voiceId);
    if (!result) return null;
    return this.pollForCompletion(result.getUrl);
  }
}
