import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 生产构建产出 standalone 产物（Docker 镜像只需 server.js + static，无需 node_modules）
  output: "standalone",

  // 生产环境移除 console（保留 error/warn 便于排障）
  compiler: {
    removeConsole:
      process.env.NODE_ENV === "production"
        ? { exclude: ["error", "warn"] }
        : false,
  },

  // 关闭构建期 X-Powered-By 头，减少指纹暴露
  poweredByHeader: false,

  // 安全响应头基线
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
