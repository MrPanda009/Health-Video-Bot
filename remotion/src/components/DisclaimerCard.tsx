import React, { useMemo } from "react";
import { AbsoluteFill } from "remotion";
import { getFontFamily } from "../utils/fontLoader";

interface Props {
  textHindi: string;
  textEnglish: string;
  fontFamily?: string;
  brandPrimaryColor?: string;
}

export const DisclaimerCard: React.FC<Props> = ({
  textHindi,
  textEnglish,
  fontFamily: rawFontFamily,
  brandPrimaryColor = "#FFD700",
}) => {
  const fontFamily = useMemo(() => getFontFamily(rawFontFamily), [rawFontFamily]);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0d0d0c",
        justifyContent: "center",
        alignItems: "center",
        padding: "40px",
        fontFamily,
      }}
    >
      <div
        style={{
          background: "rgba(25, 25, 25, 0.65)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRadius: "24px",
          padding: "48px 40px",
          maxWidth: "90%",
          textAlign: "center",
          border: `1.5px solid rgba(255, 255, 255, 0.08)`,
          boxShadow: `0 20px 50px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1)`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "24px",
        }}
      >
        {/* Editorial Credit Header / Minimalist Insignia */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "4px",
          }}
        >
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              border: `2px solid ${brandPrimaryColor}`,
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              color: brandPrimaryColor,
              fontSize: "24px",
              fontWeight: 700,
              boxShadow: `0 0 15px ${brandPrimaryColor}33`,
            }}
          >
            ⚖
          </div>
          <div
            style={{
              color: brandPrimaryColor,
              fontSize: "24px",
              fontWeight: 700,
              letterSpacing: "2px",
              textTransform: "uppercase",
              marginTop: "8px",
            }}
          >
            Editorial Note
          </div>
          <div
            style={{
              color: "rgba(255, 255, 255, 0.4)",
              fontSize: "13px",
              textTransform: "uppercase",
              letterSpacing: "1px",
            }}
          >
            Medical Information
          </div>
        </div>

        {/* Divider */}
        <div
          style={{
            width: "80px",
            height: "2px",
            background: `linear-gradient(90deg, transparent, ${brandPrimaryColor}, transparent)`,
          }}
        />

        {/* Bilingual Content */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "20px",
          }}
        >
          <div
            style={{
              color: "#ffffff",
              fontSize: "26px",
              lineHeight: 1.5,
              fontWeight: 500,
            }}
          >
            {textHindi}
          </div>
          <div
            style={{
              color: "rgba(255, 255, 255, 0.7)",
              fontSize: "18px",
              lineHeight: 1.4,
              fontStyle: "italic",
            }}
          >
            {textEnglish}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
