import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  Series,
  useVideoConfig,
} from "remotion";
import { HealthVideoProps } from "./types";
import { DisclaimerCard } from "./components/DisclaimerCard";
import { BRollSegment } from "./components/BRollSegment";
import { ScreenshotOverlay } from "./components/ScreenshotOverlay";
import { CaptionOverlay } from "./components/CaptionOverlay";
import { SubscribeButton } from "./components/SubscribeButton";
import { DynamicChart } from "./components/DynamicChart";
import { getFontFamily } from "./utils/fontLoader";

const coverStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

export const HealthVideoComposition: React.FC<HealthVideoProps> = (props) => {
  const {
    fps,
    totalDurationInFrames,
    disclaimerTextHindi,
    disclaimerTextEnglish,
    citationText,
    showBorderFrame = true,
    citationWatermarkEnabled = true,
    brandPrimaryColor = "#FFD700",
    chartData,
    segments,
    voiceoverPath,
    backgroundMusicPath,
    wordTimestamps,
    introPath,
    outroPath,
    clickSoundPath,
    bellSoundPath,
    captionCombineMs,
    fontFamily,
  } = props;

  const { width, height } = useVideoConfig();
  const disclaimerFrames = fps * 3;

  const resolvedFontFamily = useMemo(() => getFontFamily(fontFamily), [fontFamily]);

  // Subscribe button appears in the last 7 seconds
  const subscribeStartFrame = Math.max(0, totalDurationInFrames - fps * 7);
  const subscribeDuration = totalDurationInFrames - subscribeStartFrame;

  // Build Series segments
  const seriesItems: React.ReactNode[] = [];

  if (introPath) {
    seriesItems.push(
      <Series.Sequence key="intro" durationInFrames={-1}>
        <OffthreadVideo src={introPath} style={coverStyle} volume={0} />
      </Series.Sequence>
    );
  }

  seriesItems.push(
    <Series.Sequence key="disclaimer" durationInFrames={fps * 3}>
      <DisclaimerCard
        textHindi={disclaimerTextHindi}
        textEnglish={disclaimerTextEnglish}
        fontFamily={fontFamily}
        brandPrimaryColor={brandPrimaryColor}
      />
    </Series.Sequence>
  );

  for (const seg of segments) {
    const screenshotDisplayFrames = Math.round(Math.min(fps * 3, seg.durationInFrames));

    seriesItems.push(
      <Series.Sequence key={seg.name} durationInFrames={seg.durationInFrames}>
        {seg.screenshotPath ? (
          <ScreenshotOverlay
            screenshotPath={seg.screenshotPath}
            brollPaths={seg.brollPaths}
            animationType={seg.animationType}
            brollCutIntervalFrames={seg.brollCutIntervalFrames}
            durationInFrames={seg.durationInFrames}
            screenshotDisplayFrames={screenshotDisplayFrames}
          />
        ) : (
          <AbsoluteFill>
            <BRollSegment
              brollPaths={seg.brollPaths}
              animationType={seg.animationType}
              brollCutIntervalFrames={seg.brollCutIntervalFrames}
              durationInFrames={seg.durationInFrames}
            />
            {seg.name === "finding" && chartData && (
              <DynamicChart
                chartData={chartData}
                brandPrimaryColor={brandPrimaryColor}
                fontFamily={fontFamily}
              />
            )}
          </AbsoluteFill>
        )}
      </Series.Sequence>
    );
  }

  if (outroPath) {
    seriesItems.push(
      <Series.Sequence key="outro" durationInFrames={-1}>
        <OffthreadVideo src={outroPath} style={coverStyle} volume={0} />
      </Series.Sequence>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Video track */}
      <Series>{seriesItems}</Series>

      {/* Brand Border Frame Overlay */}
      {showBorderFrame && (
        <AbsoluteFill
          style={{
            pointerEvents: "none",
            border: `10px solid ${brandPrimaryColor}1a`, // subtle 10% opacity frame
            boxSizing: "border-box",
            zIndex: 90,
          }}
        />
      )}

      {/* Permanent Research Citation Watermark Overlay — visible after disclaimer */}
      {citationWatermarkEnabled && citationText && (
        <Sequence from={disclaimerFrames}>
          <div
            style={{
              position: "absolute",
              top: "35px",
              right: "35px",
              backgroundColor: "rgba(0, 0, 0, 0.45)",
              color: "rgba(255, 255, 255, 0.55)",
              padding: "6px 12px",
              borderRadius: "8px",
              fontSize: "13px",
              fontWeight: 600,
              fontFamily: resolvedFontFamily,
              border: "1px solid rgba(255, 255, 255, 0.08)",
              pointerEvents: "none",
              zIndex: 95,
            }}
          >
            {citationText}
          </div>
        </Sequence>
      )}

      {/* Voiceover — starts after disclaimer */}
      <Sequence from={disclaimerFrames}>
        <Audio src={voiceoverPath} />
      </Sequence>

      {/* Background music at 15% */}
      <Sequence from={disclaimerFrames}>
        {backgroundMusicPath && (
          <Audio src={backgroundMusicPath} volume={0.15} />
        )}
      </Sequence>

      {/* Word-highlighted captions */}
      <Sequence from={disclaimerFrames}>
        {wordTimestamps && wordTimestamps.length > 0 && (
          <CaptionOverlay
            wordTimestamps={wordTimestamps}
            captionCombineMs={captionCombineMs}
            fontFamily={fontFamily}
          />
        )}
      </Sequence>

      {/* Animated subscribe button near the end */}
      <Sequence from={subscribeStartFrame} durationInFrames={subscribeDuration}>
        <SubscribeButton clickSoundPath={clickSoundPath} bellSoundPath={bellSoundPath} />
      </Sequence>
    </AbsoluteFill>
  );
};
