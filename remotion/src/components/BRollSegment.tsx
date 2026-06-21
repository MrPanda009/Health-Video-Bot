import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Img,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";

interface Props {
  brollPaths: string[];
  animationType: "ken_burns" | "slide_in" | "zoom_punch" | "none";
  brollCutIntervalFrames: number;
  durationInFrames: number;
}

// Scale-to-fill + center-crop via CSS object-fit
const coverStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
  objectPosition: "center",
};

export const BRollSegment: React.FC<Props> = ({
  brollPaths,
  animationType,
  brollCutIntervalFrames,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const validPaths = brollPaths.filter(Boolean);
  if (validPaths.length === 0) {
    return <AbsoluteFill style={{ backgroundColor: "#111" }} />;
  }

  const clipIndex = Math.floor(frame / brollCutIntervalFrames) % validPaths.length;
  const clipPath = validPaths[clipIndex];
  const localClipStart = clipIndex * brollCutIntervalFrames;
  const localFrameInClip = frame - localClipStart;

  const kenBurnsScale =
    animationType === "ken_burns"
      ? interpolate(frame, [0, durationInFrames], [1, 1.15], {
        extrapolateRight: "clamp",
      })
      : 1;

  const zoomPunchScale =
    animationType === "zoom_punch"
      ? interpolate(frame, [0, durationInFrames], [0.95, 1.05], {
        extrapolateRight: "clamp",
      })
      : 1;

  const slideTranslateX =
    animationType === "slide_in"
      ? (() => {
        const slideFrames = Math.round(fps * 0.3);
        const outStart = durationInFrames - slideFrames;
        if (frame < slideFrames) {
          return interpolate(frame, [0, slideFrames], [100, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
        }
        if (frame > outStart) {
          return interpolate(frame, [outStart, durationInFrames], [0, -100], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
        }
        return 0;
      })()
      : 0;

  const scale = kenBurnsScale * zoomPunchScale;
  const transform = `scale(${scale}) translateX(${slideTranslateX}%)`;

  const isImage = /\.(jpg|jpeg|png|webp|bmp|tiff)$/i.test(clipPath);

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <div
        style={{
          width: "100%",
          height: "100%",
          transform,
          transformOrigin: "center center",
        }}
      >
        {isImage ? (
          <Img src={clipPath} style={coverStyle} />
        ) : (
          <OffthreadVideo
            src={clipPath}
            style={coverStyle}
            volume={0}
            startFrom={localFrameInClip}
          />
        )}
      </div>
    </AbsoluteFill>
  );
};
