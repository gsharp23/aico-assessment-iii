import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Only used for `npm run dev` outside Docker. In the container, nginx does
    // this proxying instead (see nginx.conf).
    proxy: {
      "/api": { target: "http://localhost:5000", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
