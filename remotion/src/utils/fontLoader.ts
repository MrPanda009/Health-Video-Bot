import { loadFont as loadNotoSansDevanagari } from "@remotion/google-fonts/NotoSansDevanagari";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";
import { loadFont as loadAnekDevanagari } from "@remotion/google-fonts/AnekDevanagari";
import { loadFont as loadMukta } from "@remotion/google-fonts/Mukta";
import { loadFont as loadTiroDevanagariHindi } from "@remotion/google-fonts/TiroDevanagariHindi";
import { loadFont as loadHind } from "@remotion/google-fonts/Hind";

const fontLoaders: Record<string, () => string> = {
  NotoSansDevanagari: () => loadNotoSansDevanagari("normal", { weights: ["400", "700"] }).fontFamily,
  Poppins: () => loadPoppins("normal", { weights: ["400", "700"] }).fontFamily,
  AnekDevanagari: () => loadAnekDevanagari("normal", { weights: ["400", "700"] }).fontFamily,
  Mukta: () => loadMukta("normal", { weights: ["400", "700"] }).fontFamily,
  TiroDevanagariHindi: () => loadTiroDevanagariHindi("normal", { weights: ["400"] }).fontFamily,
  Hind: () => loadHind("normal", { weights: ["400", "700"] }).fontFamily,
};

export const getFontFamily = (name?: string): string => {
  if (!name || name === "SystemFont") {
    return "'Noto Sans Devanagari', 'Arial Unicode MS', sans-serif";
  }
  const loader = fontLoaders[name];
  if (loader) {
    try {
      return loader();
    } catch (e) {
      console.warn("Failed to load font:", name, e);
    }
  }
  return "'Noto Sans Devanagari', 'Arial Unicode MS', sans-serif";
};
