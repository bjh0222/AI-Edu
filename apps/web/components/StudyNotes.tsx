"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Button, Card, inputCls } from "./ui";

type Recent = { title: string; goal: string; href: string; updated: string };
export function ContinueLearning() {
  const [recent, setRecent] = useState<Recent | null>(null);
  useEffect(() => {
    // Browser storage is unavailable during server rendering.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    try { const r = JSON.parse(localStorage.getItem("aiedu-recent-section") || "null"); if (r && /^\/tutorials\/[^/]+\/sections\/[^/]+$/.test(r.href)) setRecent(r); } catch { /* No saved reading position. */ }
  }, []);
  if (!recent) return null;
  return <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-brand/30 bg-panel p-5">
    <div><div className="text-xs font-semibold text-brand">继续上次学习</div><div className="mt-1 font-bold">{recent.title}</div><div className="mt-1 text-xs text-muted">{recent.goal}</div></div>
    <div className="flex items-center gap-3"><Link className="rounded-xl bg-brand px-4 py-2 text-sm text-white" href={recent.href}>继续阅读 →</Link><button className="text-xs text-muted" onClick={() => { try { localStorage.removeItem("aiedu-recent-section"); } catch {} setRecent(null); }}>清除记录</button></div>
  </div>;
}

export default function StudyNotes({ sectionId, tutorialId, title, goal }: { sectionId: string; tutorialId: string; title: string; goal: string }) {
  const [note, setNote] = useState("");
  const [done, setDone] = useState(false);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("");
  const key = `aiedu-study-${tutorialId}-${sectionId}`;
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "{}");
      // Restore persisted reading notes after hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNote(typeof saved.note === "string" ? saved.note : ""); setDone(saved.done === true);
      localStorage.setItem("aiedu-recent-section", JSON.stringify({ title, goal, href: `/tutorials/${tutorialId}/sections/${sectionId}`, updated: new Date().toISOString() }));
    } catch { setStatus("浏览器存储不可用，请下载笔记保留内容。"); }
    setReady(true);
  }, [key, title, goal, tutorialId, sectionId]);
  const save = (text: string, checked: boolean) => {
    setNote(text); setDone(checked);
    try { localStorage.setItem(key, JSON.stringify({ note: text, done: checked, updated: new Date().toISOString() })); setStatus("已自动保存到此浏览器"); }
    catch { setStatus("保存失败，请先下载笔记备份。"); }
  };
  const download = () => {
    const blob = new Blob([`# ${title}\n\n学习目标：${goal}\n\n阅读状态：${done ? "已读完" : "学习中"}\n\n${note}\n`], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `${title.replace(/[\\/:*?"<>|]/g, "_")}-笔记.md`; link.click(); URL.revokeObjectURL(url);
  };
  return <Card title="我的学习笔记" desc="记录自己的理解和疑问；保存在此浏览器，可单独下载备份">
    <label className="mb-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={done} disabled={!ready} onChange={e => save(note, e.target.checked)} />标记本节已读完</label>
    <textarea aria-label="本节学习笔记" className={inputCls} rows={7} maxLength={50000} placeholder="用自己的话总结；下次实践时还需要确认什么？" value={note} disabled={!ready} onChange={e => save(e.target.value, done)} />
    <div className="mt-2 flex items-center justify-between gap-2"><span role="status" className="text-xs text-muted">{status}</span><Button variant="secondary" onClick={download}>下载笔记</Button></div>
    <p className="mt-2 text-xs text-muted">已读完只记录阅读进度，不代表已通过能力验收。</p>
  </Card>;
}
