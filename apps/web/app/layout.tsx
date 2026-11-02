import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import MobileNav from "@/components/MobileNav";
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
          {/* 手机端底部标签栏固定占位，main 需留出等高内边距；桌面端 md:pb-0 抵消 */}
          <main className="min-w-0 flex-1 pb-[calc(56px+env(safe-area-inset-bottom))] md:pb-0">
            {children}
          </main>
        </div>
        {/* MobileNav 依赖 usePathname，必须包在 Suspense 内（理由同 Sidebar） */}
        {/* fallback 也要 fixed：MobileNav 本身是 fixed 占位，流内 fallback 会多撑出 56px 空白 */}
        <Suspense
          fallback={
            <nav
              aria-hidden="true"
              className="fixed inset-x-0 bottom-0 h-[calc(56px+env(safe-area-inset-bottom))] bg-navy md:hidden"
            />
          }
        >
          <MobileNav />
        </Suspense>
      </body>
    </html>
  );
}
