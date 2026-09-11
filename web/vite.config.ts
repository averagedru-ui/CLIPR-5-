import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: "./",
  plugins: [
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "CLIPR Mobile",
        short_name: "CLIPR",
        description: "Reframe 16:9 clips to 9:16 on the go",
        theme_color: "#1a2b22",
        background_color: "#12201a",
        display: "standalone",
        orientation: "portrait",
        start_url: "./",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png}"]
      }
    })
  ],
  server: {
    host: true,
    port: 5173
  }
});
