import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";

export const SubscribeButton: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // Slide up from bottom
  const slideProgress = spring({
    frame,
    fps,
    config: { mass: 0.8, damping: 15, stiffness: 100 },
    durationInFrames: Math.round(fps * 0.6),
  });

  const translateY = interpolate(slideProgress, [0, 1], [120, 0]);

  // Pulsing bell after slide-in settles
  const bellPulse =
    frame > Math.round(fps * 0.8)
      ? Math.sin(((frame - Math.round(fps * 0.8)) / fps) * Math.PI * 2) * 0.15 + 1
      : 1;

  const buttonWidth = Math.round(width * 0.65);
  const buttonHeight = Math.round(height * 0.075);
  const fontSize = Math.round(buttonHeight * 0.38);
  const bottomOffset = Math.round(height * 0.12);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          bottom: bottomOffset,
          left: "50%",
          transform: `translateX(-50%) translateY(${translateY}px)`,
          display: "flex",
          alignItems: "center",
          gap: "14px",
          backgroundColor: "#FF0000",
          borderRadius: "50px",
          paddingLeft: Math.round(buttonHeight * 0.5),
          paddingRight: Math.round(buttonHeight * 0.7),
          paddingTop: Math.round(buttonHeight * 0.2),
          paddingBottom: Math.round(buttonHeight * 0.2),
          boxShadow: "0 6px 24px rgba(0,0,0,0.5)",
          width: buttonWidth,
          justifyContent: "center",
        }}
      >
        {/* Bell icon */}
        <span
          style={{
            fontSize: Math.round(fontSize * 1.1),
            display: "inline-block",
            transform: `scale(${bellPulse})`,
            transformOrigin: "center bottom",
          }}
        >
          🔔
        </span>

        {/* Subscribe text */}
        <span
          style={{
            color: "#ffffff",
            fontSize,
            fontWeight: 800,
            fontFamily: "sans-serif",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          Subscribe
        </span>
      </div>
    </AbsoluteFill>
  );
};
