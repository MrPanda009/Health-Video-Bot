import React from "react";
import { AbsoluteFill } from "remotion";

interface Props {
  text: string;
}

export const DisclaimerCard: React.FC<Props> = ({ text }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#000",
        justifyContent: "center",
        alignItems: "center",
        padding: "60px",
      }}
    >
      <div
        style={{
          backgroundColor: "#141414",
          borderRadius: "16px",
          padding: "48px 56px",
          maxWidth: "80%",
          textAlign: "center",
        }}
      >
        <div
          style={{
            color: "#FFC800",
            fontSize: "36px",
            fontWeight: 700,
            marginBottom: "20px",
            fontFamily: "sans-serif",
          }}
        >
          ⚠ Medical Notice
        </div>
        <div
          style={{
            color: "#ffffff",
            fontSize: "30px",
            lineHeight: 1.5,
            fontFamily: "sans-serif",
          }}
        >
          {text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
