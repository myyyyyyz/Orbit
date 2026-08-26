import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

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
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
