import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import ThemeSync from "@/components/ThemeSync";
import { themeBootstrap } from "@/lib/theme";

export const metadata: Metadata = {
  title: "AI Edu · 学习工作台",
  description: "以学习目标为起点、以可执行教程和真实实践为载体、以证据反馈和独立能力验证为闭环的 AI 学习工具。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body className="min-h-full">
        <ThemeSync />
        <div className="mx-auto flex min-h-screen max-w-[1450px]">
          {/* Sidebar 依赖 useSearchParams（知识网络子目录高亮），必须包在 Suspense 内：
              否则静态外壳无法预渲染，且首屏会在客户端挂起。 */}
          <Suspense fallback={<aside className="hidden w-[238px] shrink-0 bg-navy md:block" />}>
            <Sidebar />
          </Suspense>
          <main className="min-w-0 flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
