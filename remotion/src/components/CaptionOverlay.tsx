import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { createTikTokStyleCaptions } from "@remotion/captions";
import type { Caption, TikTokPage } from "@remotion/captions";
import { WordTimestamp } from "../types";

import { getFontFamily } from "../utils/fontLoader";

// ─── Config ────────────────────────────────────────────────
const HIGHLIGHT_COLOR = "#FFD700";
const DEFAULT_COLOR = "#ffffff";

// ─── Converter ─────────────────────────────────────────────
function wordTimestampsToCaptions(words: WordTimestamp[]): Caption[] {
  return words.map((w) => ({
    text: " " + w.word,      // Leading space required by createTikTokStyleCaptions
    startMs: w.start * 1000,
    endMs: w.end * 1000,
    timestampMs: ((w.start + w.end) / 2) * 1000,
    confidence: null,
  }));
}

// ─── Single Page ───────────────────────────────────────────
const CaptionPage: React.FC<{
  page: TikTokPage;
  height: number;
  fontFamily: string;
}> = ({ page, height, fontFamily }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;
  const absoluteTimeMs = page.startMs + currentTimeMs;

  // Find last spoken word as fallback (anti-flicker)
  let lastSpokenIdx = -1;
  for (let i = 0; i < page.tokens.length; i++) {
    if (page.tokens[i].fromMs <= absoluteTimeMs) {
      lastSpokenIdx = i;
    }
  }

  const marginBottom = Math.round(height * 0.08);
  const fontSize = Math.round(height * 0.032);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          bottom: marginBottom,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          flexWrap: "wrap",
          gap: "0 6px",
          padding: "0 40px",
          whiteSpace: "pre",
        }}
      >
        {page.tokens.map((token, i) => {
          const isActive =
            token.fromMs <= absoluteTimeMs && token.toMs > absoluteTimeMs;
          const isFallback = !isActive && i === lastSpokenIdx;

          return (
            <span
              key={token.fromMs}
              style={{
                color: isActive || isFallback ? HIGHLIGHT_COLOR : DEFAULT_COLOR,
                fontSize,
                fontWeight: 700,
                fontFamily,
                textShadow:
                  "2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000",
                lineHeight: 1.3,
              }}
            >
              {token.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ─── Main Overlay ──────────────────────────────────────────
interface Props {
  wordTimestamps: WordTimestamp[];
  captionCombineMs?: number;
  fontFamily?: string;
}

export const CaptionOverlay: React.FC<Props> = ({
  wordTimestamps,
  captionCombineMs = 1500,
  fontFamily: rawFontFamily,
}) => {
  const { fps, height } = useVideoConfig();

  const fontFamily = useMemo(() => getFontFamily(rawFontFamily), [rawFontFamily]);

  const pages = useMemo(() => {
    const captions = wordTimestampsToCaptions(wordTimestamps);
    const { pages } = createTikTokStyleCaptions({
      captions,
      combineTokensWithinMilliseconds: captionCombineMs,
    });
    return pages;
  }, [wordTimestamps, captionCombineMs]);

  return (
    <AbsoluteFill>
      {pages.map((page, index) => {
        const nextPage = pages[index + 1] ?? null;
        const startFrame = Math.round((page.startMs / 1000) * fps);
        const endFrame = Math.min(
          nextPage ? Math.round((nextPage.startMs / 1000) * fps) : Infinity,
          startFrame + Math.round((captionCombineMs / 1000) * fps),
        );
        const durationInFrames = endFrame - startFrame;

        if (durationInFrames <= 0) return null;

        return (
          <Sequence key={index} from={startFrame} durationInFrames={durationInFrames}>
            <CaptionPage page={page} height={height} fontFamily={fontFamily} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
