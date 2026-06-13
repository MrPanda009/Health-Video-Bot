import React from "react";
import {
  AbsoluteFill,
  Img,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";
import { BRollSegment } from "./BRollSegment";

interface Props {
  screenshotPath: string;
  brollPaths: string[];
  animationType: "ken_burns" | "slide_in" | "zoom_punch" | "none";
  brollCutIntervalFrames: number;
  durationInFrames: number;
  screenshotDisplayFrames: number;
}

export const ScreenshotOverlay: React.FC<Props> = ({
  screenshotPath,
  brollPaths,
  animationType,
  brollCutIntervalFrames,
  durationInFrames,
  screenshotDisplayFrames,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const ssVisible = frame < screenshotDisplayFrames;
  const ssOpacity = ssVisible
    ? interpolate(
        frame,
        [screenshotDisplayFrames - 10, screenshotDisplayFrames],
        [1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
      )
    : 0;

  const ssWidth = Math.round(width * 0.8);
  const ssLeft = Math.round((width - ssWidth) / 2);

  return (
    <AbsoluteFill>
      <BRollSegment
        brollPaths={brollPaths}
        animationType="none"
        brollCutIntervalFrames={brollCutIntervalFrames}
        durationInFrames={durationInFrames}
      />
      {ssOpacity > 0 && (
        <div
          style={{
            position: "absolute",
            left: ssLeft,
            top: "50%",
            transform: "translateY(-50%)",
            width: ssWidth,
            opacity: ssOpacity,
            borderRadius: "12px",
            overflow: "hidden",
            boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
          }}
        >
          <Img
            src={screenshotPath}
            style={{ width: "100%", height: "auto", display: "block" }}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};
