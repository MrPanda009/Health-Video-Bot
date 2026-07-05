export interface WordTimestamp {
  word: string;
  start: number; // seconds
  end: number;   // seconds
}

export interface ChartMetric {
  label: string;
  value: number;
  unit: string;
}

export interface ChartData {
  chartType: "bar" | "radial" | "none";
  title: string;
  metrics: ChartMetric[];
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
  disclaimerTextHindi: string;
  disclaimerTextEnglish: string;
  citationText?: string | null;
  showBorderFrame?: boolean;
  citationWatermarkEnabled?: boolean;
  brandPrimaryColor?: string;
  chartData?: ChartData | null;
  segments: SegmentProps[];
  voiceoverPath: string;
  backgroundMusicPath?: string | null;
  wordTimestamps?: WordTimestamp[] | null;
  introPath?: string | null;
  outroPath?: string | null;
  clickSoundPath?: string | null;
  bellSoundPath?: string | null;
  transitionsEnabled: boolean;
  transitionDurationFrames: number;
  captionCombineMs?: number;
  fontFamily?: string;
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
