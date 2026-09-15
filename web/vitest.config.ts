import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

/**
 * 前端单测配置（P1-5-3）。
 *
 * 刻意与 `vite.config.ts` 分开：`vite build` 不应该把 jsdom 与测试环境拖进产物，
 * 而 vitest 需要 `environment: 'jsdom'`（组件测试要真实的 DOM、`document.activeElement`
 * 与键盘事件）。别名与生产构建保持一致，测试里可以直接 `import ... from '../src/x'`
 * 或用 `@/x`。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.spec.ts'],
    globals: false,
    restoreMocks: true,
  },
})
