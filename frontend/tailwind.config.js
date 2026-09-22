/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Light-theme neutral scale, reusing the ORIGINAL HeatSentinel
        // palette values directly (field/ink/muted/rule from the old
        // frontend's CSS) rather than inventing new ones. Named ink-950
        // (lightest) .. ink-100 (darkest) so every existing component
        // that already used this scale (for contrast pairing, e.g.
        // bg-ink-950 text-ink-100) flips to a correct light theme
        // automatically, without touching each file's class list.
        ink: {
          950: "#F7F4EC", // page background (== old --field, slightly lifted)
          900: "#FFFFFF", // topbar / raised surfaces
          850: "#FFFFFF", // card background
          800: "#FBF9F4",
          700: "#E3DCD0", // borders (== old --rule)
          600: "#D3CABB",
          500: "#B9AE9B",
          400: "#6F6A66", // muted/secondary text (== old --muted)
          300: "#57524E",
          200: "#3C3836",
          100: "#231F20", // primary text (== old --ink)
        },
        brand: {
          50: "#FDF2F6",
          200: "#F4B8D2",
          400: "#E0538F",
          500: "#D6336C",
          600: "#B8265A",
          700: "#8B004A", // the repo's original --brand -- UNCHANGED
          800: "#6E0039", // the repo's original --brand-deep -- UNCHANGED
          900: "#4A0026", // the repo's original --brand-ink -- UNCHANGED
        },
        risk: {
          low: "#10B981",
          moderate: "#F59E0B",
          high: "#F97316",
          veryhigh: "#EF4444",
          extreme: "#B91C1C",
          none: "#6B7280",
        },
      },
      fontFamily: {
        serif: ['"Source Serif 4"', "Georgia", "serif"],
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(214,51,108,0.25), 0 8px 30px -10px rgba(214,51,108,0.35)",
      },
      backgroundImage: {
        "grid-fade":
          "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(214,51,108,0.18), transparent)",
      },
      keyframes: {
        pulseSoft: {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.55 },
        },
      },
      animation: {
        pulseSoft: "pulseSoft 2.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
