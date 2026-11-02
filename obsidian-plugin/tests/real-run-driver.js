const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

const CONFIG_PATH = process.argv[2] || path.join(__dirname, "real-run-config.json");
const CONFIG = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
const VAULT = process.env.AIEDU_VERIFY_VAULT || path.join(os.tmpdir(), "ai-edu-plugin-verify-vault");
fs.mkdirSync(path.join(VAULT, "学习"), { recursive: true });

const notices = [];
const log = (msg) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${msg}`);

function el(tag) {
  const node = {
    tag, children: [], listeners: {}, style: {}, text: "", value: "", attr: {},
    createEl(t, opts = {}) { const c = el(t); if (opts.text) c.text = opts.text; if (opts.value !== undefined) c.value = opts.value; if (opts.attr) c.attr = opts.attr; if (opts.cls) c.cls = opts.cls; this.children.push(c); return c; },
    createDiv(cls) { const c = el("div"); c.cls = cls; this.children.push(c); return c; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute() {}, setText(t) { this.text = String(t); },
    empty() { this.children = []; },
    querySelector() { return null; }, remove() {}, focus() {},
    click() { return Promise.all((this.listeners.click || []).map((fn) => fn())); },
    findButtons(out = []) { this.children.forEach((c) => { if (c.tag === "button") out.push(c); c.findButtons(out); }); return out; },
  };
  return node;
}

async function requestUrl(options) {
  const res = await fetch(options.url, {
    method: options.method,
    headers: options.headers,
    body: options.body,
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch (_) {}
  const headers = {};
  res.headers.forEach((v, k) => { headers[k] = v; });
  return { status: res.status, json, text, headers };
}

class Plugin {}
class PluginSettingTab {}
class Setting { setName() { return this; } setDesc() { return this; } addText() { return this; } addDropdown() { return this; } }
class Modal { constructor(app) { this.app = app; } open() {} close() {} }
class Notice { constructor(m) { notices.push(String(m)); log(`Notice: ${m}`); } }
const normalizePath = (v) => String(v).replace(/\\/g, "/").replace(/\/+/g, "/");

const stub = { Plugin, PluginSettingTab, Setting, Modal, Notice, normalizePath, requestUrl };
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "obsidian") return stub;
  return originalLoad.call(this, request, parent, isMain);
};

const source = fs.readFileSync(path.join(__dirname, "..", "ai-edu-tutorial-delivery", "main.js"), "utf8");
const tempFile = path.join(os.tmpdir(), `ai-edu-main-verify-${process.pid}.js`);
fs.writeFileSync(tempFile, source + "\nmodule.exports.__AIEduModal = AIEduModal;\n");
const AIEduModal = require(tempFile).__AIEduModal;

const vault = {
  getAbstractFileByPath(p) { return fs.existsSync(path.join(VAULT, p)) ? { path: p } : null; },
  async create(p, content) { fs.mkdirSync(path.dirname(path.join(VAULT, p)), { recursive: true }); fs.writeFileSync(path.join(VAULT, p), content, "utf8"); return { path: p }; },
  async createFolder(p) { fs.mkdirSync(path.join(VAULT, p), { recursive: true }); },
  getMarkdownFiles() { return []; },
};

const plugin = {
  settings: { apiBaseUrl: "http://127.0.0.1:8000", folder: "学习", generationTier: "standard", formatSpecId: "auto" },
  apiBase: () => "http://127.0.0.1:8000",
  saveSettings: async () => {},
  async ensureFolder(folder) { fs.mkdirSync(path.join(VAULT, folder), { recursive: true }); },
};

const modal = Object.create(AIEduModal.prototype);
modal.plugin = plugin;
modal.app = {
  vault,
  workspace: {
    getLeaf: () => ({ openFile: async () => {} }),
    revealLeaf: () => {},
    setActiveLeaf: () => {},
  },
};
modal.contentEl = el("div");
modal.statusEl = { setText: (t) => log(`status: ${t}`) };
modal.submitEl = { disabled: false, setText: () => {} };
modal.createOnlyEl = { disabled: false };
modal.busy = false; modal.touched = false; modal.completed = false; modal.closed = false;
modal.close = () => { modal.closed = true; log("modal closed"); };

// —— 表单内容来自配置文件（默认与上次对话一致） ——
modal.titleInputEl = { value: CONFIG.title };
modal.domainEl = { value: CONFIG.domain_key };
modal.motivationEl = { value: CONFIG.motivation };
modal.applicationEl = { value: CONFIG.application_context };
modal.currentLevelEl = { value: CONFIG.current_level };
modal.hardConstraintsEl = { value: CONFIG.hard_constraints };
modal.timeBudgetEl = { value: CONFIG.time_budget };
modal.capabilityEl = { value: CONFIG.capability_level };
modal.extraEl = { checked: !!CONFIG.generate_extra_exercises };
modal.tierEl = { value: CONFIG.generation_tier };
modal.formatSpecs = [];
modal.formatSpecEl = { value: "auto", empty() {}, createEl() {}, options: [] };

// 手动选择的格式规范 id（配置提供）
const SPEC_ID = CONFIG.format_spec_id;

// 真实材料文件（配置提供绝对路径）
const docxPath = CONFIG.material_path;
const docx = fs.readFileSync(docxPath);

(async () => {
  // 仅交付模式：--deliver-only <tutorialId>，不重新生成，只把现有教程写入 Vault
  if (process.argv.includes("--deliver-only")) {
    const tutorialId = process.argv[process.argv.indexOf("--deliver-only") + 1];
    modal.tutorial = { id: tutorialId };
    modal.lastForm = { title: CONFIG.title };
    log(`仅交付模式：tutorial=${tutorialId}`);
    await AIEduModal.prototype.loadAndDeliver.call(modal);
    log(`completed=${modal.completed} savedPath=${modal.savedPath}`);
    if (modal.savedPath) {
      const md = fs.readFileSync(path.join(VAULT, modal.savedPath), "utf8");
      log(`主文档 ${modal.savedPath} 长度=${md.length}`);
      console.log("---- HEADINGS ----");
      console.log(md.split("\n").filter((l) => /^#{1,4} /.test(l)).join("\n"));
    }
    console.log("RESULT " + (modal.completed ? "OK" : "FAILED"));
    fs.unlinkSync(tempFile);
    process.exit(modal.completed ? 0 : 1);
  }

  // 打开弹窗的等价初始化：拉取规范列表（真实 HTTP），然后手动选定规范
  await AIEduModal.prototype.loadFormatSpecs.call(modal);
  log(`规范候选：${modal.formatSpecs.map((s) => s.name).join("、") || "（无）"}`);
  modal.formatSpecEl = { value: SPEC_ID };
  const form = AIEduModal.prototype.readForm.call(modal);
  log(`format_spec_id 提交值：${JSON.stringify(form.format_spec_id)}`);

  modal.pendingMaterials = [{
    key: "material-1",
    file: { name: CONFIG.material_name, size: docx.length, type: CONFIG.material_type || "application/octet-stream", arrayBuffer: async () => docx.buffer.slice(docx.byteOffset, docx.byteOffset + docx.byteLength) },
    kind: CONFIG.material_kind || "example_source",
    status: "pending",
    error: "",
  }];

  log("提交生成任务（真实后端）…");
  await AIEduModal.prototype.submit.call(modal);

  if (modal.pausedGoalId) {
    log(`AI 暂停（goal=${modal.pausedGoalId}），点击「坚决执行」续跑…`);
    const proceed = modal.contentEl.findButtons().find((b) => b.text === "坚决执行");
    if (!proceed) throw new Error("未找到坚决执行按钮");
    await proceed.click();
  }

  log(`completed=${modal.completed} savedPath=${modal.savedPath}`);
  if (modal.savedPath) {
    const md = fs.readFileSync(path.join(VAULT, modal.savedPath), "utf8");
    log(`主文档 ${modal.savedPath} 长度=${md.length}`);
    console.log("---- HEAD ----");
    console.log(md.split("\n").slice(0, 12).join("\n"));
    console.log("---- HEADINGS ----");
    console.log(md.split("\n").filter((l) => /^#{1,4} /.test(l)).join("\n"));
  }
  console.log("RESULT " + (modal.completed ? "OK" : "FAILED"));
  fs.unlinkSync(tempFile);
  process.exit(modal.completed ? 0 : 1);
})().catch((err) => { console.error("DRIVER ERROR:", err); process.exit(2); });
