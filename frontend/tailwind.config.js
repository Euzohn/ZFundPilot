/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        gain: {
          50: "var(--gain-50)", 100: "var(--gain-100)", 200: "var(--gain-200)",
          300: "var(--gain-300)", 400: "var(--gain-400)", 500: "var(--gain-500)",
          600: "var(--gain-600)", 700: "var(--gain-700)", 800: "var(--gain-800)",
          900: "var(--gain-900)", 950: "var(--gain-950)",
          DEFAULT: "var(--gain-600)",
          light: "var(--gain-500)",
        },
        loss: {
          50: "var(--loss-50)", 100: "var(--loss-100)", 200: "var(--loss-200)",
          300: "var(--loss-300)", 400: "var(--loss-400)", 500: "var(--loss-500)",
          600: "var(--loss-600)", 700: "var(--loss-700)", 800: "var(--loss-800)",
          900: "var(--loss-900)", 950: "var(--loss-950)",
          DEFAULT: "var(--loss-600)",
          light: "var(--loss-500)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Fira Sans", "system-ui", "sans-serif"],
        mono: ["Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
}
