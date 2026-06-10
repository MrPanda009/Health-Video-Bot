export interface WordTimestamp {
  word: string;
  start: number; // seconds
  end: number;   // seconds
}

export interface SegmentProps {
  name: string;
  durationInFrames: number;
  brollPaths: string[];       // absolute file paths
  screenshotPath?: string | null;
  animationType: "ken_burns" | "slide_in" | "zoom_punch" | "none";
  brollCutIntervalFrames: number;
}

export interface HealthVideoProps {
  width: number;
  height: number;
  fps: number;
  totalDurationInFrames: number;
  disclaimerText: string;
  segments: SegmentProps[];
  voiceoverPath: string;
  backgroundMusicPath?: string | null;
  wordTimestamps?: WordTimestamp[] | null;
  introPath?: string | null;
  outroPath?: string | null;
  transitionsEnabled: boolean;
  transitionDurationFrames: number;
}

export interface EDLEntry {
  timelineStart: number;   // seconds
  timelineEnd: number;     // seconds
  clipPath?: string | null;
  animationType?: string | null;
  transitionToNext?: string | null;
}

export interface EDLProps {
  baseVideoPath: string;   // absolute path
  baseDurationSeconds: number;
  fps: number;
  entries: EDLEntry[];
}
