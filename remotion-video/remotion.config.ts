import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setJpegQuality(80);
Config.setConcurrency(1);
Config.setChromiumOpenGlRenderer("swangle");
Config.setTimeoutInMilliseconds(180000);
Config.setOffthreadVideoCacheSizeInBytes(512 * 1024 * 1024); // 512MB
