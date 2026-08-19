import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Vite 預設綁 `localhost`，在 macOS 上只會聽 IPv6 的 [::1]，
    // 因此 http://127.0.0.1:5173 會直接被拒絕連線（瀏覽器不會替明確 IP 做 fallback）。
    // 明確綁 IPv4：127.0.0.1 直接可用，localhost 也仍可用（瀏覽器會退回 IPv4）。
    // 不用 `host: true`，避免把開發伺服器暴露到區域網路。
    host: '127.0.0.1',
    // 埠被占用時直接失敗，不要偷偷換到 5174 ——
    // 換了埠而 proxy 設定沒跟著換，會出現「畫面開得起來但 API 全掛」的假象。
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:2222',
        changeOrigin: true,
      },
    },
  },
})
