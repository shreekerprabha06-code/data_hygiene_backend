import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { federation } from "@module-federation/vite";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  resolve: {
    alias: {
      "@data-hygiene/ui": path.resolve(__dirname, "../packages/ui/src"),
      "@data-hygiene/core": path.resolve(__dirname, "../packages/core/src"),
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom", "react-router-dom", "@mui/material", "@emotion/react", "@emotion/styled"],
  },
  plugins: [
    react(),
    federation({
      name: "dashboard",
      filename: "remoteEntry.js",
      dts: false,
      exposes: {
        "./RecordsListPage": "./src/pages/RecordsListPage.jsx",
      },
      remotes: {
        details: {
          type: "module",
          name: "details",
          entry: "http://localhost:5002/remoteEntry.js",
        },
        auth: {
          type: "module",
          name: "auth",
          entry: "http://localhost:5004/remoteEntry.js",
        },
      },
      shared: {
        react: { singleton: true },
        "react-dom": { singleton: true },
        "react/jsx-runtime": { singleton: true },
        "react-router-dom": { singleton: true },
        "@mui/material": { singleton: true },
        "@emotion/react": { singleton: true },
        "@emotion/styled": { singleton: true },
      },
    }),
  ],
  build: {
    target: "esnext",
    minify: false,
    cssCodeSplit: false,
  },
  server: {
    port: 5001,
    strictPort: true,
  }
});
