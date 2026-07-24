import fs from "node:fs";
import path from "node:path";

const sampleRate = 48000;
const outputDir = path.resolve("public/motion-audio");
fs.mkdirSync(outputDir, {recursive: true});

const writeWav = (name, seconds, sample) => {
  const count = Math.round(seconds * sampleRate);
  const bytes = Buffer.alloc(44 + count * 2);
  bytes.write("RIFF", 0);
  bytes.writeUInt32LE(36 + count * 2, 4);
  bytes.write("WAVEfmt ", 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(sampleRate, 24);
  bytes.writeUInt32LE(sampleRate * 2, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36);
  bytes.writeUInt32LE(count * 2, 40);
  for (let index = 0; index < count; index++) {
    const time = index / sampleRate;
    const value = Math.max(-1, Math.min(1, sample(time, index)));
    bytes.writeInt16LE(Math.round(value * 32767), 44 + index * 2);
  }
  fs.writeFileSync(path.join(outputDir, name), bytes);
};

writeWav("signal-pulse.wav", 2, (time) => {
  const phase = time % 0.55;
  const envelope = phase < 0.13 ? Math.sin((phase / 0.13) * Math.PI) : 0;
  return Math.sin(2 * Math.PI * 92 * time) * envelope * 0.22;
});
writeWav("silence-drop.wav", 1, (time) => {
  const envelope = Math.max(0, 1 - time / 0.18);
  return Math.sin(2 * Math.PI * (180 - time * 120) * time) * envelope * 0.12;
});
writeWav("data-click.wav", 0.25, (time, index) => {
  const noise = (((index * 1103515245 + 12345) >>> 8) % 65536) / 32768 - 1;
  return noise * Math.exp(-time * 42) * 0.24;
});
writeWav("transition-envelope.wav", 1, (time) => {
  const envelope = Math.sin(Math.PI * time) ** 2;
  return Math.sin(2 * Math.PI * (210 + time * 430) * time) * envelope * 0.1;
});
writeWav("music-bed.wav", 8, (time) => {
  const chord = [55, 82.5, 110].reduce(
    (sum, frequency) => sum + Math.sin(2 * Math.PI * frequency * time),
    0,
  ) / 3;
  return chord * (0.035 + 0.012 * Math.sin(2 * Math.PI * time / 4));
});

console.log(`Generated deterministic motion audio in ${outputDir}`);
