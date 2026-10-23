"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Field, inputCls } from "./ui";

type Profile = { id: string; name: string; base_url: string; model: string; has_key?: boolean; api_key?: string | null; timeout: number; temperature: number | null; json_mode: boolean };
type Config = { active_id: string | null; profiles: Profile[] };
type Probe = { reply: string; model: string; latency_ms: number; demo: boolean; usage: { total_tokens: number } | null };
const blank = (): Profile => ({ id: "", name: "自定义模型", base_url: "", model: "", api_key: null, timeout: 120, temperature: .3, json_mode: true });
const presets = [
  { name: "DeepSeek", url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { name: "硅基流动", url: "https://api.siliconflow.cn/v1", model: "" },
  { name: "通义千问", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { name: "本地 Ollama", url: "http://127.0.0.1:11434/v1", model: "" },
  { name: "自定义", url: "", model: "" },
];

export default function ModelSettings() {
  const [config, setConfig] = useState<Config>({ active_id: null, profiles: [] });
  const [form, setForm] = useState<Profile>(blank);
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [probe, setProbe] = useState<Probe | null>(null);
  const [testedFingerprint, setTestedFingerprint] = useState("");
  const fingerprint = JSON.stringify(form);
  useEffect(() => {
    api.get<Config>("/api/settings/models").then(c => {
      setConfig(c); const active = c.profiles.find(p => p.id === c.active_id) ?? c.profiles[0];
      setForm(active ? { ...active, api_key: null } : { ...blank(), id: crypto.randomUUID() }); setLoaded(true);
    }).catch(e => setError(e.message));
  }, []);
  const change = (patch: Partial<Profile>) => { setForm(f => ({ ...f, ...patch })); setProbe(null); setMessage(""); setError(""); };
  const run = async (task: string, operation: () => Promise<void>) => {
    setBusy(task); setError(""); setMessage("");
    try { await operation(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  };
  const saved = config.profiles.find(p => p.id === form.id);
  const keyRetained = !!saved?.has_key && saved.base_url.replace(/\/$/, "") === form.base_url.replace(/\/$/, "");
  const payload = { ...form, api_key: form.api_key ?? null };
  const select = (p?: Profile) => { setForm(p ? { ...p, api_key: null } : { ...blank(), id: crypto.randomUUID() }); setProbe(null); setModels([]); setMessage(""); setError(""); };
  return <Card title="模型接入" desc="兼容 Chat Completions 协议 · 配置保存后，启用即可用于诊断和教程生成">
    <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
      <Badge tone={config.active_id ? "done" : "warn"}>{config.active_id ? `当前：${config.profiles.find(p => p.id === config.active_id)?.name}` : "当前：演示模式"}</Badge>
      <Button variant="secondary" disabled={!!busy || !loaded} onClick={() => select()}>＋ 新增配置</Button>
      {config.active_id && <Button variant="ghost" disabled={!!busy} onClick={() => run("demo", async () => { setConfig(await api.post<Config>("/api/settings/models/activate", { active_id: null })); setMessage("已切换到演示模式，已保存的模型配置仍保留。"); })}>切回演示模式</Button>}
    </div>
    {config.profiles.length > 0 && <div className="mb-4 flex flex-wrap gap-2" aria-label="已保存模型">
      {config.profiles.map(p => <button key={p.id} disabled={!!busy} onClick={() => select(p)} className={`rounded-lg border px-3 py-2 text-xs ${form.id === p.id ? "border-brand text-brand" : "border-line"}`}>{p.name}{p.id === config.active_id ? " · 使用中" : ""}</button>)}
    </div>}
    <fieldset disabled={!!busy || !loaded} className="min-w-0 disabled:opacity-70">
      <div className="mb-3 flex flex-wrap gap-2">{presets.map(p => <button key={p.name} className="rounded-lg bg-canvas px-3 py-1.5 text-xs" onClick={() => { select(); setForm({ ...blank(), id: crypto.randomUUID(), name: p.name, base_url: p.url, model: p.model }); }}>{p.name}</button>)}</div>
      <div className="grid gap-x-4 md:grid-cols-2">
        <Field label="配置名称"><input className={inputCls} value={form.name} onChange={e => change({ name: e.target.value })} /></Field>
        <Field label="API 根地址"><input className={inputCls} placeholder="https://api.example.com/v1" value={form.base_url} onChange={e => { change({ base_url: e.target.value }); setModels([]); }} /></Field>
      </div>
      <Field label="API Key"><input type="password" autoComplete="new-password" className={inputCls} value={form.api_key ?? ""} onChange={e => change({ api_key: e.target.value || null })} placeholder={keyRetained ? "已保存密钥；留空保持不变" : "输入密钥；本地免认证服务可留空"} /></Field>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-muted"><span>密钥仅保存在本机服务端，不随学习数据备份导出。</span>{keyRetained && <label className="flex gap-1"><input type="checkbox" checked={form.api_key === ""} onChange={e => change({ api_key: e.target.checked ? "" : null })} />清除已保存密钥</label>}</div>
      {saved?.has_key && !keyRetained && <p className="mb-3 text-xs text-amber">接口地址已更改，请重新填写密钥。</p>}
      <div className="flex items-end gap-2"><div className="min-w-0 flex-1"><Field label="模型 ID"><input className={inputCls} list="available-models" placeholder="选择或填写模型 ID" value={form.model} onChange={e => change({ model: e.target.value })} /><datalist id="available-models">{models.map(m => <option key={m} value={m} />)}</datalist></Field></div>
        <Button className="mb-3" variant="secondary" onClick={() => run("discover", async () => { const r = await api.post<{ models: string[] }>("/api/settings/models/discover", payload); setModels(r.models); setMessage(r.models.length ? `找到 ${r.models.length} 个模型，可在模型 ID 输入框中选择。` : "接口未列出模型，请手动填写 ID。"); })}>{busy === "discover" ? "获取中…" : "获取模型列表"}</Button>
      </div>
      <details className="mb-4 rounded-xl border border-line p-3"><summary className="cursor-pointer text-xs font-semibold">高级兼容设置</summary><div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="请求超时（秒）"><input className={inputCls} type="number" min="5" max="600" value={form.timeout} onChange={e => change({ timeout: Number(e.target.value) })} /></Field>
        <Field label="温度（留空使用模型默认值）"><input className={inputCls} type="number" min="0" max="2" step="0.1" value={form.temperature ?? ""} onChange={e => change({ temperature: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={form.json_mode} onChange={e => change({ json_mode: e.target.checked })} />启用 JSON 输出参数</label>
      </div><p className="mt-2 text-xs text-muted">若接口不支持 response_format，可关闭此项；教程仍会校验 JSON 内容。连接测试最多等待 60 秒。</p></details>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => run("test", async () => { setProbe(null); const r = await api.post<Probe>("/api/settings/models/test", payload); setProbe(r); setTestedFingerprint(fingerprint); })}>{busy === "test" ? "正在真实调用模型…" : "测试连接"}</Button>
        <Button variant="secondary" onClick={() => run("save", async () => { const c = await api.post<Config>("/api/settings/models", payload); setConfig(c); const p = c.profiles.find(p => p.id === form.id)!; setForm({ ...p, api_key: null }); setProbe(null); setMessage("配置已保存。点击“测试并启用”即可使用。"); })}>保存配置</Button>
        <Button onClick={() => run("activate", async () => { if (!probe || testedFingerprint !== fingerprint) { const r = await api.post<Probe>("/api/settings/models/test", payload); setProbe(r); } const c = await api.post<Config>("/api/settings/models", payload); const p = c.profiles.find(p => p.id === form.id)!; setForm({ ...p, api_key: null }); setTestedFingerprint(JSON.stringify({ ...p, api_key: null })); setConfig(await api.post<Config>("/api/settings/models/activate", { active_id: form.id })); setMessage("已通过真实请求测试并启用，新的学习生成请求立即使用此模型。"); })}>{busy === "activate" ? "测试并启用中…" : "测试并启用"}</Button>
        {saved && <Button variant="ghost" onClick={() => { if (confirm(`删除模型配置“${form.name}”？`)) void run("delete", async () => { setConfig(await api.del<Config>(`/api/settings/models/${form.id}`)); select(); }); }}>删除配置</Button>}
      </div>
    </fieldset>
    {busy && <p role="status" className="mt-3 text-xs text-muted">正在处理，请稍候…</p>}
    {error && <div role="alert" className="mt-3 rounded-xl border border-red-400/40 bg-red-500/10 p-3 text-sm">{error}</div>}
    {message && <p role="status" className="mt-3 text-sm text-teal">{message}</p>}
    {probe && <div className="mt-3 rounded-xl border border-teal/40 bg-teal/10 p-3 text-sm"><strong>真实模型连接成功</strong><p className="mt-1">{probe.reply}</p><p className="mt-1 text-xs text-muted">{probe.model} · {probe.latency_ms} ms · {probe.usage ? `${probe.usage.total_tokens} tokens` : "接口未返回用量"} · 已通过 JSON 结构验证</p></div>}
  </Card>;
}
