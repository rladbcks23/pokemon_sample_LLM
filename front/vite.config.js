import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// Django(back/) 개발 서버
const BACK = 'http://localhost:8000'
// 파티 코치 LLM 서버 (llm/)
const LLM = 'http://localhost:8001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // API와 아이콘은 Django로 넘김 (같은 주소처럼 써서 CORS 설정 불필요)
    proxy: {
      '/api': BACK,
      '/assets': BACK,
      '/llm': LLM,
    },
  },
})
