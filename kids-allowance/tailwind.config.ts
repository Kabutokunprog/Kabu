import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        cream: "#FFF8EF",
        ink: "#4A3728",
        primary: {
          DEFAULT: "#FF8FA3",
          soft: "#FFD9E2",
        },
        secondary: {
          DEFAULT: "#63C7F2",
          soft: "#D6F0FC",
        },
        mint: {
          DEFAULT: "#3FBF8F",
          soft: "#D3F5E6",
        },
        amber: {
          DEFAULT: "#F2A93C",
          soft: "#FDEBCE",
        },
      },
      fontFamily: {
        rounded: ["var(--font-rounded)", "sans-serif"],
      },
      borderRadius: {
        xl2: "1.5rem",
      },
    },
  },
  plugins: [],
};
export default config;
