import React from "react";
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

const coverStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

export const HealthVideoComposition: React.FC<HealthVideoProps> = (props) => {
  const {
    fps,
    totalDurationInFrames,
    disclaimerText,
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
      <DisclaimerCard text={disclaimerText} />
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
          <BRollSegment
            brollPaths={seg.brollPaths}
            animationType={seg.animationType}
            brollCutIntervalFrames={seg.brollCutIntervalFrames}
            durationInFrames={seg.durationInFrames}
          />
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
