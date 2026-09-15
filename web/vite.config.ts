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
        // App shell only in the precache (CacheFirst by default) - .json/
        // .vctpl used to be here too for offline template browsing, but
        // precache is served straight from cache with no per-visit
        // freshness check. A PWA reopened from the home screen (not a true
        // browser reload) can go a long time before ever noticing the
        // server has new/updated templates - confirmed as the actual cause
        // of repeated "still not seeing my new template" reports, not
        // deploy lag or a one-off stale-cache fluke. Templates now use a
        // NetworkFirst runtime strategy instead: always tries the network
        // first (so new saves show up immediately), only falls back to the
        // last cached copy when actually offline.
        globPatterns: ["**/*.{js,css,html,svg,png}"],
        runtimeCaching: [
          {
            urlPattern: /\/templates\/.*\.(json|vctpl)$/,
            handler: "NetworkFirst",
            options: {
              cacheName: "templates-cache",
              networkTimeoutSeconds: 4,
            },
          },
        ],
      }
    })
  ],
  server: {
    host: true,
    port: 5173
  }
});
