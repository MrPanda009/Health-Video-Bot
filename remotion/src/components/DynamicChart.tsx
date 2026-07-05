import React, { useMemo } from "react";
import {
  spring,
  useCurrentFrame,
  useVideoConfig,
  AbsoluteFill,
  interpolate,
} from "remotion";
import { ChartData } from "../types";
import { getFontFamily } from "../utils/fontLoader";

interface Props {
  chartData: ChartData;
  brandPrimaryColor?: string;
  fontFamily?: string;
}

export const DynamicChart: React.FC<Props> = ({
  chartData,
  brandPrimaryColor = "#FFD700",
  fontFamily: rawFontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  const fontFamily = useMemo(() => getFontFamily(rawFontFamily), [rawFontFamily]);

  const { chartType, title, metrics } = chartData;

  // Global entry animation for the chart card container (slide up + fade in)
  const cardSpring = spring({
    frame,
    fps,
    config: { damping: 15 },
  });
  
  const cardOpacity = interpolate(cardSpring, [0, 1], [0, 1]);
  const cardTranslateY = interpolate(cardSpring, [0, 1], [40, 0]);

  // Find max value to scale bar widths correctly (default to 100 if all values are small)
  const maxMetricValue = useMemo(() => {
    const vals = metrics.map((m) => m.value);
    const maxVal = Math.max(...vals, 0);
    return maxVal > 100 ? maxVal : 100;
  }, [metrics]);

  const renderBarChart = () => {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "24px", width: "100%" }}>
        {metrics.map((m, index) => {
          // Stagger bar entries
          const delay = index * 8;
          const barSpring = spring({
            frame: Math.max(0, frame - delay - 10), // start after card slides in
            fps,
            config: { damping: 13, stiffness: 80 },
          });

          const currentWidthPercent = m.value / maxMetricValue * 100;
          const animatedWidth = interpolate(barSpring, [0, 1], [0, currentWidthPercent]);
          const labelOpacity = interpolate(barSpring, [0, 0.4, 1], [0, 0.5, 1]);

          return (
            <div key={index} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  color: "#ffffff",
                  fontSize: "20px",
                  fontWeight: 600,
                  opacity: labelOpacity,
                }}
              >
                <span>{m.label}</span>
                <span style={{ color: brandPrimaryColor }}>
                  {m.value}
                  {m.unit}
                </span>
              </div>
              
              {/* Bar Track */}
              <div
                style={{
                  width: "100%",
                  height: "18px",
                  backgroundColor: "rgba(255, 255, 255, 0.12)",
                  borderRadius: "9px",
                  overflow: "hidden",
                  border: "1px solid rgba(255, 255, 255, 0.05)",
                }}
              >
                {/* Active Filled Bar */}
                <div
                  style={{
                    width: `${animatedWidth}%`,
                    height: "100%",
                    background: `linear-gradient(90deg, ${brandPrimaryColor}aa, ${brandPrimaryColor})`,
                    borderRadius: "9px",
                    boxShadow: `0 0 10px ${brandPrimaryColor}44`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderRadialChart = () => {
    // Circle math
    const radius = 65;
    const strokeWidth = 14;
    const circumference = 2 * Math.PI * radius; // ~408.4

    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "20px",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "32px" }}>
          {metrics.map((m, index) => {
            const delay = index * 12;
            const progressSpring = spring({
              frame: Math.max(0, frame - delay - 10),
              fps,
              config: { damping: 15, stiffness: 70 },
            });

            // Target percentage of the ring to fill (clamp to 100%)
            const percentFraction = Math.min(m.value / 100, 1);
            const targetFill = percentFraction * circumference;
            const currentStrokeOffset = circumference - interpolate(progressSpring, [0, 1], [0, targetFill]);

            return (
              <div
                key={index}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  position: "relative",
                  width: "150px",
                }}
              >
                {/* SVG Ring */}
                <svg width="150" height="150" style={{ transform: "rotate(-90deg)" }}>
                  {/* Track Circle */}
                  <circle
                    cx="75"
                    cy="75"
                    r={radius}
                    fill="transparent"
                    stroke="rgba(255, 255, 255, 0.1)"
                    strokeWidth={strokeWidth}
                  />
                  {/* Highlight Fill Ring */}
                  <circle
                    cx="75"
                    cy="75"
                    r={radius}
                    fill="transparent"
                    stroke={brandPrimaryColor}
                    strokeWidth={strokeWidth}
                    strokeDasharray={circumference}
                    strokeDashoffset={currentStrokeOffset}
                    strokeLinecap="round"
                    style={{
                      filter: `drop-shadow(0 0 5px ${brandPrimaryColor}55)`,
                    }}
                  />
                </svg>

                {/* Text in Center */}
                <div
                  style={{
                    position: "absolute",
                    top: "75px",
                    left: "75px",
                    transform: "translate(-50%, -63%)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    color: "#ffffff",
                  }}
                >
                  <span style={{ fontSize: "28px", fontWeight: 700, color: brandPrimaryColor }}>
                    {m.value}
                    {m.unit}
                  </span>
                </div>

                {/* Label below SVG */}
                <span
                  style={{
                    marginTop: "12px",
                    color: "#ffffff",
                    fontSize: "18px",
                    fontWeight: 600,
                    textAlign: "center",
                  }}
                >
                  {m.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const ssWidth = Math.round(width * 0.88);
  const ssLeft = Math.round((width - ssWidth) / 2);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: ssLeft,
          top: "45%",
          transform: `translateY(-50%) translateY(${cardTranslateY}px)`,
          width: ssWidth,
          opacity: cardOpacity,
          background: "rgba(20, 20, 20, 0.72)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderRadius: "24px",
          padding: "36px 28px",
          border: "1.5px solid rgba(255, 255, 255, 0.08)",
          boxShadow: "0 25px 50px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255, 255, 255, 0.1)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "28px",
          fontFamily,
        }}
      >
        {/* Title */}
        <div style={{ textAlign: "center" }}>
          <h3
            style={{
              margin: 0,
              color: brandPrimaryColor,
              fontSize: "24px",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "1px",
            }}
          >
            {title}
          </h3>
          <div
            style={{
              width: "50px",
              height: "2px",
              backgroundColor: brandPrimaryColor,
              margin: "10px auto 0 auto",
              opacity: 0.6,
            }}
          />
        </div>

        {/* Content render based on type */}
        {chartType === "radial" ? renderRadialChart() : renderBarChart()}
      </div>
    </AbsoluteFill>
  );
};
