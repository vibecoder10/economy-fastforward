import {createHash} from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {spawnSync} from "node:child_process";

const sourceKeys = {
  image: "approved:staged:image:opening",
  video: "approved:staged:video:opening",
  audio: "approved:staged:audio:opening",
};

const digest = (value) => createHash("sha256").update(value).digest("hex");
const root = path.resolve("public/custom-film-sources");
const imagePath = path.join(root, "image", `${digest(sourceKeys.image)}.png`);
const videoPath = path.join(root, "video", `${digest(sourceKeys.video)}.mp4`);
const audioPath = path.join(root, "audio", `${digest(sourceKeys.audio)}.wav`);

for (const target of [imagePath, videoPath, audioPath]) {
  fs.mkdirSync(path.dirname(target), {recursive: true});
}

const run = (args) => {
  const result = spawnSync("ffmpeg", ["-y", "-loglevel", "error", ...args], {
    stdio: "inherit",
  });
  if (result.status !== 0) throw new Error(`ffmpeg fixture generation failed: ${args.join(" ")}`);
};

run([
  "-f", "lavfi",
  "-i", "color=c=0x092127:s=1920x1080",
  "-vf", "drawbox=x=220:y=180:w=1480:h=720:color=0x2de2d0@0.35:t=12,drawbox=x=680:y=360:w=560:h=260:color=0x102f35:t=fill",
  "-frames:v", "1",
  imagePath,
]);

run([
  "-f", "lavfi",
  "-i", "testsrc2=size=1920x1080:rate=24:duration=2",
  "-f", "lavfi",
  "-i", "sine=frequency=330:sample_rate=48000:duration=2",
  "-vf", "hue=s=0.35,drawbox=x=656:y=0:w=608:h=1080:color=0x2de2d0@0.16:t=10",
  "-map", "0:v",
  "-map", "1:a",
  "-c:v", "libx264",
  "-c:a", "aac",
  "-ar", "48000",
  "-ac", "2",
  "-pix_fmt", "yuv420p",
  "-movflags", "+faststart",
  "-metadata", "comment=StoryEngine deterministic staged proof",
  videoPath,
]);

fs.copyFileSync(path.resolve("public/motion-audio/signal-pulse.wav"), audioPath);
console.log(`Generated staged image/video/audio fixtures in ${root}`);
