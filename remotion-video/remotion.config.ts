import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setJpegQuality(70);
Config.setConcurrency(3);
Config.setChromiumOpenGlRenderer("swangle");
Config.setTimeoutInMilliseconds(180000);
Config.setOffthreadVideoCacheSizeInBytes(1024 * 1024 * 1024); // 1GB
