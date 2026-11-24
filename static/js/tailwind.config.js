/*
 * IHMS — Tailwind design tokens ("Clinical Indigo").
 * Loaded after the Tailwind Play CDN so tokens are available globally.
 * Source of truth: docs/DESIGN.md §2, §3.
 */
tailwind.config = {
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#EEF2FF",
          100: "#E0E7FF",
          200: "#C7D2FE",
          400: "#818CF8",
          500: "#4F46E5",
          600: "#4338CA",
          700: "#3730A3",
          900: "#1E1B4B",
        },
        clinical: {
          50: "#F0FDFA",
          100: "#CCFBF1",
          400: "#2DD4BF",
          500: "#14B8A6",
          600: "#0D9488",
        },
        surface: "#FFFFFF",
        page: "#F8FAFC",
        muted: "#F1F5F9",
        dept: {
          opd: "#6366F1",
          ipd: "#8B5CF6",
          icu: "#DC2626",
          emergency: "#F97316",
          lab: "#06B6D4",
          pharmacy: "#22C55E",
          billing: "#EAB308",
          ot: "#EC4899",
        },
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans Bengali", "system-ui", "sans-serif"],
        display: ["Manrope", "Noto Sans Bengali", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        xl: "14px",
        "2xl": "20px",
      },
      boxShadow: {
        sm: "0 1px 2px rgba(15,23,42,0.04)",
        md: "0 4px 12px rgba(15,23,42,0.06)",
        lg: "0 12px 32px rgba(15,23,42,0.10)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        pulseDot: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "fade-up": "fade-up 150ms ease-out",
        shimmer: "shimmer 1.5s infinite",
        "pulse-dot": "pulseDot 1.6s ease-in-out infinite",
      },
    },
  },
};
