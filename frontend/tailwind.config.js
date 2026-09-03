/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#F8FAFC",
        card: "#FFFFFF",
        foreground: "#0F172A",
        muted: "#F1F5F9",
        "muted-fg": "#64748B",
        border: "#E2E8F0",
        primary: "#1E40AF",
        accent: "#059669",
        warning: "#D97706",
        destructive: "#DC2626",
      },
      fontFamily: {
        sans: ['"Fira Sans"', "system-ui", "sans-serif"],
        mono: ['"Fira Code"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.04)",
      },
    },
  },
  plugins: [],
};
