import {createHash} from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const fixtureDir = path.resolve("test-fixtures/director-scene-proof");
const outputDir = path.resolve("public/director-scene-proof");
const manifestPath = path.join(fixtureDir, "manifest.json");
const controlManifestPath = path.resolve(
  "src/custom-film/scene-control-proof-control-manifest.json",
);

const canonicalJson = (value) => {
  const compareCodePoints = (left, right) => {
    const a = Array.from(left, (character) => character.codePointAt(0));
    const b = Array.from(right, (character) => character.codePointAt(0));
    for (let index = 0; index < Math.min(a.length, b.length); index++) {
      if (a[index] !== b[index]) return a[index] - b[index];
    }
    return a.length - b.length;
  };
  const normalize = (item) =>
    Array.isArray(item)
      ? item.map(normalize)
      : item && typeof item === "object"
        ? Object.fromEntries(
            Object.entries(item)
              .sort(([left], [right]) => compareCodePoints(left, right))
              .map(([key, child]) => [key, normalize(child)]),
          )
        : item;
  return JSON.stringify(normalize(value));
};

const digestCanonical = (value) =>
  createHash("sha256").update(canonicalJson(value)).digest("hex");

if (!fs.existsSync(manifestPath)) {
  throw new Error(`Tracked Scene Control fixture manifest is missing: ${manifestPath}`);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const controlManifest = JSON.parse(
  fs.readFileSync(controlManifestPath, "utf8"),
);
for (const key of [
  "asset_evidence",
  "director_contract",
  "storyboard_gate",
  "picture_gate",
  "visual_gate",
  "admission",
]) {
  const entry = controlManifest[key];
  if (!entry || digestCanonical(entry.payload) !== entry.sha256) {
    throw new Error(`Scene Control canonical ${key} evidence changed`);
  }
}
if (
  controlManifest.storyboard_gate.payload.director_contract_hash !==
    controlManifest.director_contract.sha256 ||
  controlManifest.picture_gate.payload.storyboard_gate_hash !==
    controlManifest.storyboard_gate.sha256 ||
  controlManifest.visual_gate.payload.picture_gate_hash !==
    controlManifest.picture_gate.sha256 ||
  controlManifest.admission.payload.visual_gate_hash !==
    controlManifest.visual_gate.sha256
) {
  throw new Error("Scene Control canonical gate dependency changed");
}
const {manifest_sha256: manifestHash, ...controlBody} = controlManifest;
if (digestCanonical(controlBody) !== manifestHash) {
  throw new Error("Scene Control canonical manifest identity changed");
}
const names = Object.keys(manifest).sort();
if (names.length !== 9) {
  throw new Error("Scene Control fixture manifest must bind five clips and four voices");
}

fs.mkdirSync(outputDir, {recursive: true});
for (const name of names) {
  if (path.basename(name) !== name) {
    throw new Error(`Scene Control fixture name is unsafe: ${name}`);
  }
  const source = path.join(fixtureDir, name);
  const expected = manifest[name];
  const bytes = fs.readFileSync(source);
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expected) {
    throw new Error(
      `Tracked Scene Control fixture hash changed for ${name}: ${actual}`,
    );
  }
  fs.copyFileSync(source, path.join(outputDir, name));
}
fs.copyFileSync(manifestPath, path.join(outputDir, "manifest.json"));
const proofHashes = Object.values(manifest).sort();
const evidenceHashes = [
  ...controlManifest.asset_evidence.payload.clips.map((row) => row[1]),
  ...controlManifest.asset_evidence.payload.voices.map((row) => row[2]),
].sort();
if (JSON.stringify(proofHashes) !== JSON.stringify(evidenceHashes)) {
  throw new Error("Scene Control proof bytes diverge from canonical evidence");
}
for (const [name, expected] of controlManifest.asset_evidence.payload
  .motion_audio) {
  const actual = createHash("sha256")
    .update(fs.readFileSync(path.resolve("public/motion-audio", name)))
    .digest("hex");
  if (actual !== expected) {
    throw new Error(`Scene Control motion-audio evidence changed: ${name}`);
  }
}
const browserDir = path.resolve(
  "../storyengine/frontend/public/scene-control-proof",
);
const browserManifest = JSON.parse(
  fs.readFileSync(path.join(browserDir, "manifest.json"), "utf8"),
);
const {
  manifest_sha256: browserManifestHash,
  ...browserManifestBody
} = browserManifest;
if (
  digestCanonical(browserManifestBody) !== browserManifestHash ||
  browserManifest.control_manifest_sha256 !== controlManifest.manifest_sha256
) {
  throw new Error("Scene Control browser artifact manifest changed");
}
for (const artifact of [
  browserManifest.composition,
  ...browserManifest.shots,
]) {
  const name = path.basename(artifact.url);
  const actual = createHash("sha256")
    .update(fs.readFileSync(path.join(browserDir, name)))
    .digest("hex");
  if (actual !== artifact.sha256) {
    throw new Error(`Scene Control browser artifact changed: ${name}`);
  }
}
console.log(
  `Verified canonical identity and staged ${names.length} Scene Control proof assets in ${outputDir}`,
);
