import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  Img,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";
import { EDLProps } from "./types";

const IMAGE_EXTS = /\.(jpg|jpeg|png|webp|bmp|tiff)$/i;

const coverStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

function KenBurnsClip({ src, durationInFrames }: { src: string; durationInFrames: number }) {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, durationInFrames], [1, 1.15], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <div style={{ width: "100%", height: "100%", transform: `scale(${scale})`, transformOrigin: "center" }}>
        <Img src={src} style={coverStyle} />
      </div>
    </AbsoluteFill>
  );
}

interface BRollClipProps {
  clipPath: string;
  animationType?: string | null;
  durationInFrames: number;
}

function BRollClip({ clipPath, animationType, durationInFrames }: BRollClipProps) {
  const isImage = IMAGE_EXTS.test(clipPath);
  const anim = animationType || (isImage ? "ken_burns" : "none");

  if (isImage && anim === "ken_burns") {
    return <KenBurnsClip src={clipPath} durationInFrames={durationInFrames} />;
  }

  if (isImage) {
    return (
      <AbsoluteFill>
        <Img src={clipPath} style={coverStyle} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill>
      <OffthreadVideo src={clipPath} style={coverStyle} volume={0} />
    </AbsoluteFill>
  );
}

export const EDLComposition: React.FC<EDLProps> = ({
  baseVideoPath,
  baseDurationSeconds,
  fps,
  entries,
}) => {
  const totalFrames = Math.round(baseDurationSeconds * fps);

  return (
    <AbsoluteFill>
      {/* Base video — full duration, audio kept */}
      <OffthreadVideo
        src={baseVideoPath}
        style={coverStyle}
      />

      {/* B-roll overlays — muted, placed at EDL start frames */}
      {entries.map((entry, i) => {
        if (!entry.clipPath) return null;
        const startFrame = Math.round(entry.timelineStart * fps);
        const endFrame = Math.min(Math.round(entry.timelineEnd * fps), totalFrames);
        const duration = endFrame - startFrame;
        if (duration <= 0) return null;

        return (
          <Sequence key={i} from={startFrame} durationInFrames={duration}>
            <BRollClip
              clipPath={entry.clipPath}
              animationType={entry.animationType}
              durationInFrames={duration}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
