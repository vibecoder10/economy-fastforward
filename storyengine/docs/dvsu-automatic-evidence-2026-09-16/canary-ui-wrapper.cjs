#!/usr/bin/env node
/* One Holland-only call through the actual frontend API wrapper; no retries. */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const ts = require(path.resolve(__dirname, "../../frontend/node_modules/typescript"));

const root = path.resolve(__dirname, "../..");
const mode = process.argv[2] || "";
if (mode !== "--check" && mode !== "--run" && mode !== "--run-editorial") {
  throw new Error("Usage: node canary-ui-wrapper.cjs --check|--run|--run-editorial");
}

process.env.NODE_ENV = "production";
process.env.NEXT_PUBLIC_API_URL = "https://storyengine.dev";
process.env.NEXT_PUBLIC_RUBRIC_URL = "";

require.extensions[".ts"] = (module, filename) => {
  const source = fs.readFileSync(filename, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2017,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.NodeJs,
      esModuleInterop: true,
    },
    fileName: filename,
  });
  module._compile(compiled.outputText, filename);
};

const apiPath = path.resolve(root, "frontend/src/lib/api.ts");
const { runMachineScriptPreview } = require(apiPath);
if (typeof runMachineScriptPreview !== "function") {
  throw new Error("runMachineScriptPreview export is unavailable");
}

if (mode === "--check") {
  process.stdout.write(JSON.stringify({ ok: true, export: "runMachineScriptPreview", network_requests: 0 }) + "\n");
  process.exit(0);
}

const runFiles = mode === "--run-editorial"
  ? {
      stage: "ui_editorial",
      marker: "canary-ui-editorial-started.json",
      response: "canary-ui-editorial-response.json",
      requests: "canary-ui-editorial-requests.json",
    }
  : {
      stage: "ui_wrapper",
      marker: "canary-ui-wrapper-started.json",
      response: "canary-ui-wrapper-response.json",
      requests: "canary-ui-wrapper-requests.json",
    };
const markerPath = path.join(__dirname, runFiles.marker);
const responsePath = path.join(__dirname, runFiles.response);
const requestsPath = path.join(__dirname, runFiles.requests);
const videoId = "44dbf2b2-a27a-47ea-a608-4c31c906be9a";
const machine = "SS-1 — USS Holland";

const markerFd = fs.openSync(markerPath, "wx");
fs.writeFileSync(markerFd, JSON.stringify({ stage: runFiles.stage, video_id: videoId, machine }));
fs.closeSync(markerFd);

const token = execFileSync("./scripts/se.sh", ["token"], {
  cwd: root,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
}).trim();
const tenantId = JSON.parse(fs.readFileSync(path.join(__dirname, "../preview-label-2026-09-16/workspace.json"), "utf8")).tenant_id;
const storage = new Map([["token", token], ["se_active_tenant", tenantId]]);
const localStorage = {
  getItem: (key) => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
};
global.localStorage = localStorage;
global.window = {
  localStorage,
  location: { href: "" },
};

const originalFetch = global.fetch;
const requests = [];
global.fetch = async (input, init) => {
  const startedAt = Date.now();
  const request = input instanceof Request ? input : null;
  const url = typeof input === "string" ? input : request ? request.url : String(input);
  const method = init?.method || request?.method || "GET";
  const entry = { method, path: new URL(url).pathname, status: null, duration_ms: null, error_type: null };
  try {
    const response = await originalFetch(input, init);
    entry.status = response.status;
    return response;
  } catch (error) {
    entry.error_type = error && error.constructor ? error.constructor.name : "Error";
    throw error;
  } finally {
    entry.duration_ms = Date.now() - startedAt;
    requests.push(entry);
  }
};

(async () => {
  try {
    const result = await runMachineScriptPreview(videoId, machine, true);
    fs.writeFileSync(responsePath, JSON.stringify({ ok: true, result }));
    fs.writeFileSync(requestsPath, JSON.stringify(requests));
    process.stdout.write(JSON.stringify({ ok: true, request_count: requests.length }) + "\n");
  } catch (error) {
    fs.writeFileSync(responsePath, JSON.stringify({
      ok: false,
      error: {
        type: error && error.constructor ? error.constructor.name : "Error",
        status: typeof error?.status === "number" ? error.status : null,
        code: typeof error?.code === "string" ? error.code : null,
        message: error instanceof Error ? error.message : String(error),
      },
    }));
    fs.writeFileSync(requestsPath, JSON.stringify(requests));
    process.stdout.write(JSON.stringify({ ok: false, request_count: requests.length }) + "\n");
    process.exitCode = 1;
  }
})();
