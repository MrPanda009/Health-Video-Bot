import React from "react";
import { Composition } from "remotion";
import { HealthVideoComposition } from "./HealthVideoComposition";
import { EDLComposition } from "./EDLComposition";
import { HealthVideoProps, EDLProps } from "./types";

// Default props used in Remotion Studio preview
const defaultHealthProps: HealthVideoProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  totalDurationInFrames: 2700, // 90s
  disclaimerText:
    "This video is for educational purposes only. Consult your doctor before making any health decisions.",
  disclaimerTextHindi: "यह वीडियो केवल शैक्षिक उद्देश्यों के लिए है। किसी भी स्वास्थ्य संबंधी निर्णय के लिए अपने चिकित्सक से परामर्श लें।",
  disclaimerTextEnglish: "This video is for educational purposes only. Consult your doctor before making any health decisions.",
  citationText: "PMID: 12345678",
  showBorderFrame: true,
  citationWatermarkEnabled: true,
  brandPrimaryColor: "#FFD700",
  chartData: null,
  segments: [
    {
      name: "hook",
      durationInFrames: 240,
      brollPaths: [],
      animationType: "ken_burns",
      brollCutIntervalFrames: 150,
    },
  ],
  voiceoverPath: "",
  transitionsEnabled: false,
  transitionDurationFrames: 12,
};

const defaultEDLProps: EDLProps = {
  baseVideoPath: "",
  baseDurationSeconds: 10,
  fps: 30,
  entries: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HealthVideoComposition"
        component={HealthVideoComposition as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={defaultHealthProps.totalDurationInFrames}
        fps={defaultHealthProps.fps}
        width={defaultHealthProps.width}
        height={defaultHealthProps.height}
        defaultProps={defaultHealthProps as unknown as Record<string, unknown>}
        calculateMetadata={async ({ props: p }) => {
          const props = p as unknown as HealthVideoProps;
          return {
            durationInFrames: props.totalDurationInFrames,
            fps: props.fps,
            width: props.width,
            height: props.height,
          };
        }}
      />
      <Composition
        id="EDLComposition"
        component={EDLComposition as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={Math.round(defaultEDLProps.baseDurationSeconds * defaultEDLProps.fps)}
        fps={defaultEDLProps.fps}
        width={1920}
        height={1080}
        defaultProps={defaultEDLProps as unknown as Record<string, unknown>}
        calculateMetadata={async ({ props: p }) => {
          const props = p as unknown as EDLProps;
          return {
            durationInFrames: Math.round(props.baseDurationSeconds * props.fps),
            fps: props.fps,
          };
        }}
      />
    </>
  );
};
