import type { Config } from "tailwindcss";

const config: Config = {
  // The whole of src/ — a directory-list here is a trap: the arena module
  // (src/arena/) shipped with invisible stat bars because its utility classes
  // (h-1.5, bg-white/10) appeared nowhere in the two listed directories and
  // were silently never generated. Scanning extra non-Tailwind files (src/pet,
  // src/lib) costs a little JIT time and no output.
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
      },
    },
  },
  plugins: [],
};
export default config;
