import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // 开发环境允许通过 127.0.0.1 访问 HMR 等 dev 资源
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // 同源反向代理：浏览器只请求 /api/*（页面同源），由 Next 服务端转发到 FastAPI。
  // 避免浏览器跨源请求 127.0.0.1:8000 时被系统代理/跨源策略拦截。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
