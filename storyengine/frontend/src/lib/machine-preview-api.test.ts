import { readFileSync } from "node:fs";
import { describe, expect, it, afterEach, vi } from "vitest";

const videoId = "video-1";
const machine = "SS-2 USS Plunger";
const tenant = "tenant-1";
const key = `machine-preview-job:${tenant}:${videoId}:${machine}`;
const id = "123e4567-e89b-42d3-a456-426614174000";

class Storage {
  values = new Map<string, string>();
  getItem = (name: string) => this.values.get(name) ?? null;
  setItem = (name: string, value: string) => this.values.set(name, String(value));
  removeItem = (name: string) => { this.values.delete(name); };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

async function subject(storage = new Storage()) {
  vi.resetModules();
  process.env.NEXT_PUBLIC_API_URL = "https://api.test";
  process.env.NEXT_PUBLIC_RUBRIC_URL = "";
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage, location: { pathname: "/", href: "" } });
  storage.setItem("token", "test-token");
  storage.setItem("se_active_tenant", tenant);
  return { storage, ...(await import("./api")) };
}

function startBody(init?: RequestInit) {
  return JSON.parse(String(init?.body || "{}"));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("durable machine-preview API wrapper", () => {
  it("starts once then returns the exact completed job preview", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (init?.method === "POST") return json({ id, status: "pending" });
      const requestId = url.split("/").at(-1);
      return json({ id: requestId, status: "completed", result: { preview: { paragraph: "exact preview" } } });
    }));
    const api = await subject();
    await expect(api.runMachineScriptPreview(videoId, machine, true)).resolves.toEqual({ preview: { paragraph: "exact preview" } });
    expect(calls.filter(call => call.init?.method === "POST")).toHaveLength(1);
    expect(startBody(calls[0].init).request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(calls.filter(call => !call.init?.method)).toHaveLength(1);
    expect(api.storage.getItem(key)).toBeNull();
  });

  it("recovers a lost POST acknowledgement by polling the same stored id without retrying", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (init?.method === "POST") throw new TypeError("gateway lost acknowledgement");
      const requestId = url.split("/").at(-1);
      return json({ id: requestId, status: "completed", result: { preview: { paragraph: "recovered" } } });
    }));
    const api = await subject();
    await expect(api.runMachineScriptPreview(videoId, machine, true)).resolves.toEqual({ preview: { paragraph: "recovered" } });
    expect(calls.filter(call => call.init?.method === "POST")).toHaveLength(1);
    expect(calls.filter(call => !call.init?.method)).toHaveLength(1);
  });

  it("uses a saved request id for a GET-only resume", async () => {
    const storage = new Storage(); storage.setItem(key, id);
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(init?.method).not.toBe("POST");
      expect(url).toContain(`/${id}`);
      return json({ id, status: "completed", result: { preview: { paragraph: "resumed" } } });
    });
    vi.stubGlobal("fetch", fetch);
    const api = await subject(storage);
    await expect(api.runMachineScriptPreview(videoId, machine, true)).resolves.toEqual({ preview: { paragraph: "resumed" } });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("propagates terminal missing-preview and needs-review warnings", async () => {
    for (const job of [
      { id, status: "completed", result: {} },
      { id, status: "needs_review", result: { warnings: ["missing design evidence", "needs source"] } },
    ]) {
      vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") return json({ id, status: "pending" });
        return json({ ...job, id: url.split("/").at(-1) });
      }));
      const api = await subject();
      await expect(api.runMachineScriptPreview(videoId, machine, true)).rejects.toThrow(job.status === "completed" ? "Preview job completed" : "missing design evidence; needs source");
      vi.unstubAllGlobals();
    }
  });

  it("rejects a wrong returned job id immediately", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST" ? json({ id, status: "pending" }) : json({ id: "wrong", status: "running" })));
    const api = await subject();
    await expect(api.runMachineScriptPreview(videoId, machine, true)).rejects.toThrow("identity mismatch");
    expect(api.storage.getItem(key)).not.toBeNull();
  });

  it("continues through a transient 504 GET and returns the same job", async () => {
    vi.useFakeTimers();
    let gets = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return json({ id, status: "pending" });
      gets += 1;
      return gets === 1 ? json({ detail: "gateway" }, 504) : json({ id: _url.split("/").at(-1), status: "completed", result: { preview: { paragraph: "after gateway" } } });
    }));
    const api = await subject();
    const assertion = expect(api.runMachineScriptPreview(videoId, machine, true)).resolves.toEqual({ preview: { paragraph: "after gateway" } });
    await vi.advanceTimersByTimeAsync(3000);
    await assertion;
    expect(gets).toBe(2);
  });

  it("clears the pending id for definitive preview_not_started but retains it for uncertain 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => json({ code: "preview_not_started", detail: "not started" }, 400)));
    let api = await subject();
    await expect(api.runMachineScriptPreview(videoId, machine, true)).rejects.toThrow("not started");
    expect(api.storage.getItem(key)).toBeNull();

    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") throw new TypeError("ack unknown");
      return json({ detail: "unknown" }, 404);
    }));
    api = await subject();
    await expect(api.runMachineScriptPreview(videoId, machine, true)).rejects.toThrow("acknowledgement is uncertain");
    expect(api.storage.getItem(key)).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("keeps preparable as a paid-preview exception while no-spend handlers require ready", () => {
    for (const sourcePath of [
      new URL("../components/production/ScriptVoiceTab.tsx", import.meta.url),
      new URL("../components/production/ResearchTab.tsx", import.meta.url),
    ]) {
      const source = readFileSync(sourcePath, "utf8");
      expect(source).toContain("if (!readiness.ready) {");
      expect(source).toContain("if (!readiness.ready && !readiness.preparable) {");
      expect(source).toContain("Run paid single-machine script preview");
    }
  });
});
