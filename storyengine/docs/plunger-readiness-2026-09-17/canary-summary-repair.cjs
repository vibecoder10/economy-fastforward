#!/usr/bin/env node
/* Plunger-only summary-repair durable-preview harness. --check is fully offline. */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const ts = require(path.resolve(__dirname, "../../frontend/node_modules/typescript"));

const root = path.resolve(__dirname, "../..");
const mode = process.argv[2];
if (!["--check", "--run", "--resume"].includes(mode)) throw new Error("Usage: canary.cjs --check|--run|--resume");
const videoId = "44dbf2b2-a27a-47ea-a608-4c31c906be9a";
const machine = "SS-2 USS Plunger";
const tenant = "561b872d-7b73-45e3-9c44-7f30c3566eda";
const expectedKey = `machine-preview-job:${tenant}:${videoId}:${machine}`;
const marker = path.join(__dirname, "canary-summary-repair-started.json");
const responsePath = path.join(__dirname, "canary-summary-repair-response.json");
const requestPath = path.join(__dirname, "canary-summary-repair-requests.json");
const jobsPath = path.join(__dirname, "canary-summary-repair-preview-jobs.json");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

process.env.NODE_ENV = "production";
process.env.NEXT_PUBLIC_API_URL = "https://storyengine.dev";
// The wrapper must not send browser telemetry during a canary.
process.env.NEXT_PUBLIC_RUBRIC_URL = "";
require.extensions[".ts"] = (module, filename) => {
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2017, module: ts.ModuleKind.CommonJS, esModuleInterop: true }, fileName: filename });
  module._compile(output.outputText, filename);
};
const api = require(path.join(root, "frontend/src/lib/api.ts"));
if (typeof api.checkMachineScriptPreviewReadiness !== "function" || typeof api.runMachineScriptPreview !== "function") throw new Error("actual preview wrapper exports unavailable");

const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf8"));
const atomicWriteJson = (file, data) => {
  const temp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(data, null, 2) + "\n");
  fs.renameSync(temp, file);
};
const previewEntries = (memory) => Object.fromEntries([...memory].filter(([key]) => key.startsWith("machine-preview-job:")));
const persistPreviewJobs = (memory) => atomicWriteJson(jobsPath, previewEntries(memory));
const validateResumeState = () => {
  if (!fs.existsSync(marker) || !fs.existsSync(jobsPath)) throw new Error("resume requires marker and saved preview job id; refusing a second POST");
  const savedMarker = readJson(marker);
  if (savedMarker.video_id !== videoId || savedMarker.machine !== machine || savedMarker.tenant_id !== tenant) throw new Error("resume marker does not match the exact Plunger tenant/video target");
  const savedJobs = readJson(jobsPath);
  if (!savedJobs || typeof savedJobs !== "object" || Array.isArray(savedJobs) || Object.keys(savedJobs).length !== 1 || !UUID.test(String(savedJobs[expectedKey] || ""))) throw new Error("resume requires exactly one valid UUID for the expected tenant/video/SS-2 preview key");
  return savedJobs;
};

if (mode === "--check") {
  if (fs.existsSync(jobsPath) && /token|authorization/i.test(fs.readFileSync(jobsPath, "utf8"))) throw new Error("preview job storage contains forbidden credential text");
  process.stdout.write(JSON.stringify({ ok: true, target: machine, expected_preview_key: expectedKey, exports: ["checkMachineScriptPreviewReadiness", "runMachineScriptPreview"], network_requests: 0, token_persisted: false, rubric_url: process.env.NEXT_PUBLIC_RUBRIC_URL }) + "\n");
  process.exit(0);
}
if (mode === "--run" && fs.existsSync(marker)) throw new Error("started marker already exists; use --resume only");
const savedJobs = mode === "--resume" ? validateResumeState() : {};
const fd = mode === "--run" ? fs.openSync(marker, "wx") : null;
if (fd !== null) {
  fs.writeFileSync(fd, JSON.stringify({ tenant_id: tenant, video_id: videoId, machine, stage: "durable_preview_started" }) + "\n");
  fs.closeSync(fd);
}
const token = execFileSync("./scripts/se.sh", ["token"], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
if (!token || token.startsWith("no token")) throw new Error("private token unavailable");
const memory = new Map([["token", token], ["se_active_tenant", tenant]]);
for (const [key, value] of Object.entries(savedJobs)) memory.set(key, String(value));
const storage = {
  getItem: (key) => memory.get(key) || null,
  setItem: (key, value) => { memory.set(key, String(value)); if (key.startsWith("machine-preview-job:")) persistPreviewJobs(memory); },
  removeItem: (key) => { memory.delete(key); if (key.startsWith("machine-preview-job:")) persistPreviewJobs(memory); },
};
global.localStorage = storage; global.window = { localStorage: storage, location: { href: "" } };
const originalFetch = global.fetch;
const priorRequests = mode === "--resume" && fs.existsSync(requestPath) ? readJson(requestPath) : [];
if (!Array.isArray(priorRequests)) throw new Error("existing request log is invalid; refusing to overwrite it");
const requests = [...priorRequests]; let starts = 0;
global.fetch = async (input, init) => {
  const started = Date.now(); const url = typeof input === "string" ? input : input.url; const method = init?.method || input.method || "GET";
  const entry = { method, path: new URL(url).pathname, status: null, duration_ms: null };
  if (method === "POST" && entry.path.endsWith(`/machine-script-preview-jobs/${videoId}`)) {
    starts += 1;
    if (mode === "--resume") throw new Error("resume attempted a preview start POST; refusing duplicate spend");
    if (starts > 1) throw new Error("unexpected second preview start");
  }
  try { const response = await originalFetch(input, init); entry.status = response.status; return response; }
  finally { entry.duration_ms = Date.now() - started; requests.push(entry); atomicWriteJson(requestPath, requests); }
};
(async () => {
  try {
    let readiness = null;
    // A continuation reads its durable request even if current readiness drifted.
    if (mode === "--run") {
      readiness = await api.checkMachineScriptPreviewReadiness(videoId, machine);
      if (!readiness?.ready && !readiness?.preparable) throw new Error("preview preflight is neither ready nor preparable; refusing paid start");
    }
    const result = await api.runMachineScriptPreview(videoId, machine, true);
    atomicWriteJson(responsePath, { ok: true, readiness, result });
    atomicWriteJson(requestPath, requests);
    process.stdout.write(JSON.stringify({ ok: true, starts, request_count: requests.length }) + "\n");
  } catch (error) {
    atomicWriteJson(responsePath, { ok: false, error: String(error) });
    atomicWriteJson(requestPath, requests);
    throw error;
  }
})();
