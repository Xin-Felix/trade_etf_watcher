import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'

/**
 * 产物必须是「单个自包含 HTML」：
 * 页面通过 QWebEngineView.setHtml(html, QUrl("qrc:/web/")) 加载，
 * origin 是 qrc:，没有真正的 host，任何外部资源请求都拿不到
 * （webtab.py 还显式关了 LocalContentCanAccessRemoteUrls）。
 * 所以 JS/CSS 全部内联，不做 code splitting。
 */
export default defineConfig({
  plugins: [vue(), viteSingleFile()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // 输出到 frontend/dist，再由 scripts/build_frontend.sh 拷成
    // watcher/gui/web/app.html 并编译进 qrc。
    // 不直接写 watcher/gui/web/，避免 emptyOutDir 误删 echarts.min.js 等既有资源。
    outDir: 'dist',
    emptyOutDir: true,
    // 全部内联：图片/字体也不要单独产文件
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 2000,
    // 不设 rollupOptions.output.inlineDynamicImports：
    // viteSingleFile 已经关掉了 code splitting，再设会触发一条无意义的 WARN
  },
})
