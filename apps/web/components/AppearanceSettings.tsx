"use client";
import { useEffect, useState } from "react";
import { applyTheme, readTheme, saveTheme, themeDefaults, ThemePreferences } from "@/lib/theme";
import { Button, Card } from "./ui";

export default function AppearanceSettings() {
  const [prefs, setPrefs] = useState(themeDefaults);
  const [error, setError] = useState("");
  useEffect(() => {
    const sync = () => setPrefs(readTheme());
    sync();
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const update = (next: ThemePreferences) => {
    setPrefs(next); applyTheme(next);
    try { saveTheme(next); setError(""); } catch { setError("浏览器无法保存设置，本次预览仍然有效。"); }
  };
  return <Card title="外观与阅读" desc="即时生效，自动记住此浏览器的偏好">
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="主题模式">
        {([["light", "☀ 亮色"], ["dark", "☾ 暗色"], ["system", "跟随系统"]] as const).map(([mode, label]) =>
          <button key={mode} aria-pressed={prefs.mode === mode} className={`rounded-xl border px-4 py-2 text-sm ${prefs.mode === mode ? "border-brand bg-brand text-white" : "border-line bg-panel"}`} onClick={() => update({ ...prefs, mode })}>{label}</button>)}
      </div>
      <div className="flex flex-wrap items-center gap-3"><span className="text-xs font-semibold">主题色</span>
        {["#6d5dfc", "#2563eb", "#0d9488", "#c2410c", "#db2777"].map(accent => <button key={accent} aria-label={`主题色 ${accent}`} aria-pressed={prefs.accent === accent} className="h-8 w-8 rounded-full border-2 border-line outline-offset-2 aria-pressed:outline aria-pressed:outline-2" style={{ background: accent }} onClick={() => update({ ...prefs, accent })} />)}
        <label className="flex items-center gap-2 text-xs">自定义<input aria-label="自定义主题色" type="color" value={prefs.accent} onChange={e => update({ ...prefs, accent: e.target.value })} className="h-9 w-10 cursor-pointer rounded" /><span>{prefs.accent}</span></label>
      </div>
      <label className="flex items-center gap-3 text-xs">教程正文字号
        <select aria-label="教程正文字号" className="rounded-lg border border-line bg-panel p-2" value={prefs.readingSize} onChange={e => update({ ...prefs, readingSize: Number(e.target.value) })}>
          {[14, 16, 18, 20].map(n => <option key={n} value={n}>{n} px</option>)}
        </select>
      </label>
      <div className="rounded-xl border border-line bg-canvas p-4"><div className="mb-1 font-semibold text-brand">阅读预览</div><p style={{ fontSize: prefs.readingSize }}>把知识用于实践，让每一次学习都有收获。</p></div>
      <div><Button variant="secondary" onClick={() => update(themeDefaults)}>恢复默认外观</Button></div>
      {error && <p role="alert">{error}</p>}
    </div>
  </Card>;
}
