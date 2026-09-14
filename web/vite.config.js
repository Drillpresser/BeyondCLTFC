import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" keeps asset + fetch paths relative so the build works on GitHub
// Pages project sites (served under /<repo>/) without hardcoding the repo name.
export default defineConfig({
  base: "./",
  plugins: [react()],
});
