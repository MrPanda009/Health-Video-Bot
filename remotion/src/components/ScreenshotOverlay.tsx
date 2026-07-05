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

  // Dynamic Ken Burns pan and scale animation over the display duration
  const scale = interpolate(
    frame,
    [0, screenshotDisplayFrames],
    [1.0, 1.15],
    { extrapolateRight: "clamp" }
  );

  const translateY = interpolate(
    frame,
    [0, screenshotDisplayFrames],
    [0, -25],
    { extrapolateRight: "clamp" }
  );

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
            borderRadius: "16px",
            overflow: "hidden",
            border: "1.5px solid rgba(255, 255, 255, 0.15)",
            boxShadow: "0 25px 50px rgba(0,0,0,0.7)",
          }}
        >
          <Img
            src={screenshotPath}
            style={{
              width: "100%",
              height: "auto",
              display: "block",
              transform: `scale(${scale}) translateY(${translateY}px)`,
            }}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};
