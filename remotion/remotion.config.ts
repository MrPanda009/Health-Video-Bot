import os from "os";
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);

// Use the GPU: Metal-backed ANGLE renderer in headless Chromium instead of
// software SwiftShader. Speeds up compositing, CSS transforms/filters, captions.
// Fall back to "swangle" (software default) if a render ever crashes in GL.
Config.setChromiumOpenGlRenderer("angle");

// Hardware-accelerated H.264 decode (macOS VideoToolbox) for B-roll OffthreadVideo.
// "if-possible" degrades to software per-clip if a clip is unsupported.
Config.setHardwareAcceleration("if-possible");

// Render frames in parallel. M-series has many cores; ~half is the sweet spot —
// each worker is a Chromium tab, and this leaves headroom for the encoder.
Config.setConcurrency(Math.max(2, Math.floor(os.cpus().length / 2)));

// Larger off-thread video frame cache so B-roll frames aren't re-decoded across cuts.
Config.setOffthreadVideoCacheSizeInBytes(2 * 1024 * 1024 * 1024); // 2 GB
