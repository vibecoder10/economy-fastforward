#!/usr/bin/env node
/* SS-2 class-assessment refresh harness. --check is fully offline. */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const ts = require(path.resolve(__dirname, "../../frontend/node_modules/typescript"));

const root = path.resolve(__dirname, "../..");
const mode = process.argv[2];
if (!["--check", "--run"].includes(mode)) throw new Error("Usage: class-assessment-refresh.cjs --check|--run");
const videoId = "44dbf2b2-a27a-47ea-a608-4c31c906be9a";
const machine = "SS-2 USS Plunger";
const tenant = "561b872d-7b73-45e3-9c44-7f30c3566eda";
const sourceUrls = [
];
const markerPath = path.join(__dirname, "class-assessment-refresh-started.json");
const responsePath = path.join(__dirname, "class-assessment-refresh-response.json");
const requestsPath = path.join(__dirname, "class-assessment-refresh-requests.json");
const uncertainReadbackPath = path.join(__dirname, "class-assessment-refresh-uncertain-db-readback.txt");
const apiUrl = "https://storyengine.dev";
const route = `/api/pipeline/machine-research-one/${videoId}`;

process.env.NODE_ENV = "production";
process.env.NEXT_PUBLIC_API_URL = apiUrl;
process.env.NEXT_PUBLIC_RUBRIC_URL = "";
require.extensions[".ts"] = (module, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2017, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
    fileName: filename,
  });
  module._compile(output.outputText, filename);
};
const api = require(path.join(root, "frontend/src/lib/api.ts"));
if (typeof api.checkMachineScriptPreviewReadiness !== "function") throw new Error("actual frontend readiness export unavailable");

const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n");
const appendRequest = (requests, entry) => { requests.push(entry); writeJson(requestsPath, requests); };
const readbackAfterUncertainAcknowledgement = () => {
  const sql = "SELECT json_build_object('id', id, 'updated_at', updated_at, 'ss2_validation', research_payload->'unit_research_hold_validation', 'ss2_recovery', research_payload->'machine_raw_source_packages'->'SS2'->'claim_assessment'->'dvsu_recovery') FROM videos WHERE id = '44dbf2b2-a27a-47ea-a608-4c31c906be9a' AND tenant_id = '561b872d-7b73-45e3-9c44-7f30c3566eda';";
  try {
    const output = execFileSync("./scripts/se.sh", ["db", sql], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    fs.writeFileSync(uncertainReadbackPath, output);
    return { attempted: true, saved: true };
  } catch (error) {
    fs.writeFileSync(uncertainReadbackPath, `readback failed: ${String(error)}\n`);
    return { attempted: true, saved: false, error: String(error) };
  }
};

if (mode === "--check") {
  process.stdout.write(JSON.stringify({
    ok: true, target: machine, video_id: videoId, tenant_id: tenant,
    route, purpose: "saved_evidence_assessment", source_urls: sourceUrls, max_wait_ms: 600_000,
    readiness_followup_only: true, network_requests: 0, token_persisted: false,
  }) + "\n");
  process.exit(0);
}
if (fs.existsSync(markerPath)) throw new Error("class-assessment refresh marker already exists; refusing any second POST");
const fd = fs.openSync(markerPath, "wx");
fs.writeFileSync(fd, JSON.stringify({ tenant_id: tenant, video_id: videoId, machine, purpose: "saved_evidence_assessment", source_urls: sourceUrls, stage: "saved_evidence_assessment_started" }) + "\n");
fs.closeSync(fd);
const token = execFileSync("./scripts/se.sh", ["token"], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
if (!token || token.startsWith("no token")) throw new Error("private token unavailable");
const memory = new Map([["token", token], ["se_active_tenant", tenant]]);
const storage = { getItem: key => memory.get(key) || null, setItem: (key, value) => memory.set(key, String(value)), removeItem: key => memory.delete(key) };
global.localStorage = storage;
global.window = { localStorage: storage, location: { pathname: "/", href: "" } };
const requests = [];
const requestBody = { machine, confirmed_paid_run: true };

(async () => {
  let response;
  let started;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 600_000);
    started = Date.now();
    try {
      response = await fetch(apiUrl + route, {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "X-Active-Tenant": tenant },
        body: JSON.stringify(requestBody),
      });
    } catch (error) {
      const readback = readbackAfterUncertainAcknowledgement();
      appendRequest(requests, { method: "POST", path: route, status: null, duration_ms: Date.now() - started, acknowledgement: "uncertain", source_url_count: sourceUrls.length });
      writeJson(responsePath, { ok: false, phase: "post_acknowledgement_uncertain", error: String(error), db_readback: readback });
      throw new Error("class-assessment refresh acknowledgement is uncertain; DB readback saved and no resend is permitted");
    } finally {
      clearTimeout(timeout);
    }
    const text = await response.text();
    appendRequest(requests, { method: "POST", path: route, status: response.status, duration_ms: Date.now() - started, acknowledgement: "received", source_url_count: sourceUrls.length });
    let body; try { body = JSON.parse(text); } catch { body = { raw_response: text.slice(0, 4000) }; }
    writeJson(responsePath, { ok: response.ok, phase: "synchronous_research", status: response.status, response: body });
    if (!response.ok) throw new Error(`class-assessment refresh returned HTTP ${response.status}`);
  } catch (error) {
    if (!fs.existsSync(responsePath)) writeJson(responsePath, { ok: false, phase: "harness", error: String(error) });
    throw error;
  }
  // The only automatic follow-up is a no-spend actual frontend readiness read.
  const readinessStarted = Date.now();
  try {
    const readiness = await api.checkMachineScriptPreviewReadiness(videoId, machine);
    appendRequest(requests, { method: "POST", path: `/api/pipeline/machine-script-preview-readiness/${videoId}`, status: 200, duration_ms: Date.now() - readinessStarted, purpose: "no_spend_readiness" });
    const saved = JSON.parse(fs.readFileSync(responsePath, "utf8"));
    saved.readiness = readiness;
    writeJson(responsePath, saved);
    process.stdout.write(JSON.stringify({ ok: true, refresh_status: saved.status, readiness: { ready: readiness.ready, preparable: readiness.preparable, missing_fields: readiness.missing_fields || [] } }) + "\n");
  } catch (error) {
    appendRequest(requests, { method: "POST", path: `/api/pipeline/machine-script-preview-readiness/${videoId}`, status: null, duration_ms: Date.now() - readinessStarted, purpose: "no_spend_readiness", error: String(error) });
    const saved = JSON.parse(fs.readFileSync(responsePath, "utf8"));
    saved.readiness_error = String(error);
    writeJson(responsePath, saved);
    throw error;
  }
})();
