"use client";
import { useEffect } from "react";
import { applyTheme, readTheme } from "@/lib/theme";

export default function ThemeSync() {
  useEffect(() => {
    const sync = () => applyTheme(readTheme());
    sync();
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", sync);
    window.addEventListener("storage", sync);
    return () => { media.removeEventListener("change", sync); window.removeEventListener("storage", sync); };
  }, []);
  return null;
}
