import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Easing,
} from "remotion";

// Classic white arrow (pointer) cursor — tip at the top-left (~0,0).
const ArrowCursor: React.FC<{ size: number }> = ({ size }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    style={{ display: "block", filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.5))" }}
  >
    <path
      d="M3 2 L3 19 L7.5 14.8 L10.2 21 L13 19.8 L10.4 13.8 L17 13.6 Z"
      fill="#ffffff"
      stroke="#1a1a1a"
      strokeWidth={1.3}
      strokeLinejoin="round"
    />
  </svg>
);

// Pointing-hand ("click") cursor — fingertip at the top (~8,0).
const HandCursor: React.FC<{ size: number }> = ({ size }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    style={{ display: "block", filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.5))" }}
  >
    <path
      d="M8 2.6 C8 1.7 9.4 1.7 9.4 2.6 L9.4 10 L9.4 8.6 C9.4 7.8 10.7 7.8 10.7 8.6 L10.7 10.1
         C10.7 9.4 12 9.4 12 10.1 L12 10.7 C12 10 13.3 10 13.3 10.7 L13.3 14.5
         C13.3 17.8 11.6 20.4 8.6 20.4 C6.6 20.4 5.5 19.3 4.6 17.4 L3.1 14
         C2.7 13 4 12.3 4.7 13.2 L5.9 14.7 L5.9 5.2 C5.9 4.3 8 4.3 8 5.2 Z"
      fill="#ffffff"
      stroke="#1a1a1a"
      strokeWidth={1.1}
      strokeLinejoin="round"
    />
  </svg>
);

export const SubscribeButton: React.FC<{
  clickSoundPath?: string | null;
  bellSoundPath?: string | null;
}> = ({ clickSoundPath, bellSoundPath }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // ── Timeline ────────────────────────────────────────────────────────────────
  const slideInFrames = Math.round(fps * 0.6);
  const cursorStart = Math.round(fps * 0.7);
  const cursorTravelEnd = Math.round(fps * 1.4); // click frame
  const handStartFrame = cursorTravelEnd - 2; // morph to hand just before contact
  const bellRingFrame = cursorTravelEnd + Math.round(fps * 0.2);

  // ── Button geometry ──────────────────────────────────────────────────────────
  const buttonWidth = Math.round(width * 0.65);
  const buttonHeight = Math.round(height * 0.075);
  const fontSize = Math.round(buttonHeight * 0.38);
  const bottomOffset = Math.round(height * 0.12);
  const paddingLeft = Math.round(buttonHeight * 0.5);
  const bellFontSize = Math.round(fontSize * 1.1);

  // Slide up from bottom
  const slideProgress = spring({
    frame,
    fps,
    config: { mass: 0.8, damping: 15, stiffness: 100 },
    durationInFrames: slideInFrames,
  });
  const translateY = interpolate(slideProgress, [0, 1], [120, 0]);

  // ── Bell ring: decaying rotation oscillation, only after bellRingFrame ─────────
  let bellRotate = 0;
  if (frame >= bellRingFrame) {
    const t = (frame - bellRingFrame) / fps;
    const decay = Math.exp(-t / 0.6);
    bellRotate = Math.sin(t * Math.PI * 2 * 4) * 18 * decay;
  }

  // ── Cursor travel ─────────────────────────────────────────────────────────────
  // Target: the bell, sitting at the left of the horizontally-centered button.
  const bellTargetX = width / 2 - buttonWidth / 2 + paddingLeft + bellFontSize / 2;
  const bellTargetY = height - bottomOffset - buttonHeight / 2 + translateY;

  const cursorSize = Math.round(buttonHeight * 0.95);
  const travel = interpolate(frame, [cursorStart, cursorTravelEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Off-screen bottom-right → bell
  const cursorX = interpolate(travel, [0, 1], [width * 0.92, bellTargetX - cursorSize * 0.33]);
  const cursorYBase = interpolate(travel, [0, 1], [height * 1.02, bellTargetY - cursorSize * 0.05]);
  // Press dip on click
  const pressDip = interpolate(
    frame,
    [cursorTravelEnd, cursorTravelEnd + 3, cursorTravelEnd + 8],
    [0, cursorSize * 0.12, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const pressScale = interpolate(
    frame,
    [cursorTravelEnd, cursorTravelEnd + 3, cursorTravelEnd + 8],
    [1, 0.88, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const cursorY = cursorYBase + pressDip;
  const cursorOpacity = interpolate(
    frame,
    [bellRingFrame + Math.round(fps * 0.8), bellRingFrame + Math.round(fps * 1.1)],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const showHand = frame >= handStartFrame;

  // ── Click ripple at the bell ───────────────────────────────────────────────────
  const rippleProgress = interpolate(
    frame,
    [cursorTravelEnd, cursorTravelEnd + 10],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const rippleVisible = frame >= cursorTravelEnd && frame <= cursorTravelEnd + 10;
  const rippleSize = interpolate(rippleProgress, [0, 1], [bellFontSize * 0.6, bellFontSize * 2.2]);
  const rippleOpacity = interpolate(rippleProgress, [0, 1], [0.5, 0]);

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
          paddingLeft,
          paddingRight: Math.round(buttonHeight * 0.7),
          paddingTop: Math.round(buttonHeight * 0.2),
          paddingBottom: Math.round(buttonHeight * 0.2),
          boxShadow: "0 6px 24px rgba(0,0,0,0.5)",
          width: buttonWidth,
          justifyContent: "center",
        }}
      >
        {/* Bell icon — rings after the click */}
        <span
          style={{
            fontSize: bellFontSize,
            display: "inline-block",
            transform: `rotate(${bellRotate}deg)`,
            transformOrigin: "center top",
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

      {/* Click ripple over the bell */}
      {rippleVisible && (
        <div
          style={{
            position: "absolute",
            left: bellTargetX - rippleSize / 2,
            top: bellTargetY - rippleSize / 2,
            width: rippleSize,
            height: rippleSize,
            borderRadius: "50%",
            border: "3px solid rgba(255,255,255,0.9)",
            opacity: rippleOpacity,
          }}
        />
      )}

      {/* Moving cursor: arrow → pointing hand on click */}
      <div
        style={{
          position: "absolute",
          left: cursorX,
          top: cursorY,
          opacity: cursorOpacity,
          transform: `scale(${pressScale})`,
          transformOrigin: "top left",
        }}
      >
        {showHand ? <HandCursor size={cursorSize} /> : <ArrowCursor size={cursorSize} />}
      </div>

      {/* Sound cues — frames are relative to the subscribe sequence */}
      {clickSoundPath && (
        <Sequence from={cursorTravelEnd} durationInFrames={Math.round(fps)}>
          <Audio src={clickSoundPath} />
        </Sequence>
      )}
      {bellSoundPath && (
        <Sequence from={bellRingFrame} durationInFrames={Math.round(fps * 2)}>
          <Audio src={bellSoundPath} />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
