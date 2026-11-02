import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // Long model calls and multi-step generation must outlive the default 30s proxy timeout.
  experimental: { proxyTimeout: 3_600_000 },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // 开发环境允许访问 HMR 等 dev 资源的主机名。
  // 默认只放开本机；手机在同一 Wi-Fi 下访问 http://<电脑局域网IP>:3001 时，
  // Next 会因 origin 不在白名单而拒绝 dev 资源（页面能开但热更新/脚本被拦）。
  // 用「启动 AI Edu.cmd -Mobile」启动时，脚本会把局域网 IP 写进 AIEDU_DEV_ORIGINS。
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    ...(process.env.AIEDU_DEV_ORIGINS ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  ],
  // 同源反向代理：浏览器只请求 /api/*（页面同源），由 Next 服务端转发到 FastAPI。
  // 避免浏览器跨源请求 127.0.0.1:8000 时被系统代理/跨源策略拦截。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_BACKEND_URL ?? "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
