import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 只保留这一份配置。原先同时存在 vitest.config.ts 与 vitest.config.mts：
// vitest 只会加载其中一个，另一份形同死配置；而 .ts 在没有 "type": "module"
// 的 package.json 下会被当作 CommonJS 加载，启动时报
// "ESM syntax in a file loaded as CommonJS"。用 .mts 明确声明 ESM 即可消除。
// 内容取原先 vitest.config.ts 的完整版（覆盖 test/ 与 src/ 两处测试）。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    // 两份 setup 各司其职：
    // src/test/setup.ts —— jest-dom matcher + RTL cleanup（组件测试）
    // test/setup.ts     —— localStorage / next-navigation mock（API 客户端测试）
    setupFiles: ["./src/test/setup.ts", "./test/setup.ts"],
    // 覆盖两处测试：test/（API 客户端）与 src/（组件与工作台）
    include: [
      "test/**/*.test.{ts,tsx}",
      "src/**/*.test.{ts,tsx}",
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
