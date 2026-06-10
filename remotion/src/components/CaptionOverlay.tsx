import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { WordTimestamp } from "../types";

interface WordChunk {
  words: string[];
  starts: number[]; // seconds
  ends: number[];
  chunkStart: number;
  chunkEnd: number;
}

function buildChunks(words: WordTimestamp[], maxWords = 5): WordChunk[] {
  const chunks: WordChunk[] = [];
  let i = 0;
  while (i < words.length) {
    const slice = words.slice(i, i + maxWords);
    chunks.push({
      words: slice.map((w) => w.word),
      starts: slice.map((w) => w.start),
      ends: slice.map((w) => w.end),
      chunkStart: slice[0].start,
      chunkEnd: slice[slice.length - 1].end,
    });
    i += maxWords;
  }
  return chunks;
}

interface Props {
  wordTimestamps: WordTimestamp[];
}

export const CaptionOverlay: React.FC<Props> = ({ wordTimestamps }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const currentSec = frame / fps;

  const chunks = buildChunks(wordTimestamps);
  const activeChunk = chunks.find(
    (c) => currentSec >= c.chunkStart && currentSec <= c.chunkEnd
  );

  if (!activeChunk) return null;

  const activeWordIdx = activeChunk.starts.findIndex(
    (s, i) => currentSec >= s && currentSec <= activeChunk.ends[i]
  );

  const marginBottom = Math.round(height * 0.08);
  const fontSize = Math.round(height * 0.028); // ~54px at 1920h

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
          gap: "0 10px",
          padding: "0 40px",
        }}
      >
        {activeChunk.words.map((word, i) => (
          <span
            key={i}
            style={{
              color: i === activeWordIdx ? "#FFD700" : "#ffffff",
              fontSize,
              fontWeight: 700,
              fontFamily: "'Noto Sans Devanagari', 'Arial Unicode MS', sans-serif",
              textShadow:
                "2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000",
              lineHeight: 1.3,
            }}
          >
            {word}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
