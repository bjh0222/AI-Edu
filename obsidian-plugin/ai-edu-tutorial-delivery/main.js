"use strict";

const {
  Plugin,
  PluginSettingTab,
  Setting,
  Modal,
  Notice,
  normalizePath,
  requestUrl,
} = require("obsidian");

const DEFAULT_SETTINGS = {
  apiBaseUrl: "http://127.0.0.1:8000",
  folder: "学习",
  generationTier: "standard",
};

// 与后端 services/api/app/learning/disciplines.py 的 SUBJECTS（S01–S21）保持一致
const DOMAINS = [
  { key: "math_logic", label: "数学、逻辑与统计" },
  { key: "cs_it", label: "计算机科学与信息技术" },
  { key: "physics_astronomy", label: "物理与天文学" },
  { key: "chemistry_materials", label: "化学与材料" },
  { key: "biology_life", label: "生物与生命科学" },
  { key: "earth_environment", label: "地球、环境与气候" },
  { key: "engineering_manufacturing", label: "工程与制造" },
  { key: "health_sport", label: "医学、健康与运动" },
  { key: "agriculture_food", label: "农业、食品与兽医" },
  { key: "psychology_cognition", label: "心理与认知科学" },
  { key: "society_politics", label: "社会、政治与人类学" },
  { key: "economics_business", label: "经济、商业与管理" },
  { key: "law_policy", label: "法律、政策与治理" },
  { key: "education_learning", label: "教育与学习科学" },
  { key: "language_communication", label: "语言、语言学与传播" },
  { key: "philosophy_ethics", label: "哲学、伦理与宗教研究" },
  { key: "history_culture", label: "历史、文化与考古" },
  { key: "arts_creativity", label: "文学、艺术与创意实践" },
  { key: "design_architecture", label: "设计与建筑环境" },
  { key: "geography_urban", label: "地理、空间与城市研究" },
  { key: "interdisciplinary", label: "跨学科与综合研究" },
];

// 与 apps/web/lib/types.ts 的 CAPABILITY_LEVELS 保持一致
const CAPABILITY_LEVELS = [
  {
    key: "L1",
    name: "基础理解",
    description: "快速建立知识基础，理解核心概念；能解释概念、识别术语与功能、看懂简单示例。",
  },
  {
    key: "L2",
    name: "独立应用",
    description: "能独立完成典型任务；会识别常见错误、理解方法适用条件并按情境选择方法。",
  },
  {
    key: "L3",
    name: "深入掌握与迁移",
    description: "深入理解原理与概念关系；能比较方法、处理变式任务并解释关键决策依据。",
  },
];

// 与 apps/web/lib/types.ts 的 GENERATION_TIERS 保持一致
const GENERATION_TIERS = [
  { key: "fast", name: "快速", description: "单个概念、命令或小任务的直接教程。" },
  { key: "standard", name: "标准", description: "完整工作流或概念体系的默认生成深度。" },
  { key: "deep", name: "深度", description: "复杂主题、项目实践或需要严格验证的主题。" },
];

function safeName(value) {
  const cleaned = String(value || "AI Edu 教程")
    .replace(/\.md$/i, "")
    .replace(/[\\/:*?"<>|#^[\]]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
  return (cleaned || "AI Edu 教程").slice(0, 120);
}

async function readJson(response) {
  try {
    return response.json;
  } catch (_) {
    try {
      return JSON.parse(response.text);
    } catch (__) {
      return null;
    }
  }
}

function requestErrorMessage(data, response) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (detail && detail.message) return detail.message;
  if (data && data.message) return data.message;
  return `AI Edu API HTTP ${response.status}`;
}

function fileNameFromResponse(response, fallback) {
  const headers = (response && response.headers) || {};
  const disposition = headers["content-disposition"] || headers["Content-Disposition"] || "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ""));
    } catch (_) {
      return encoded[1];
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  if (plain) {
    try {
      return decodeURIComponent(plain[1].trim());
    } catch (_) {
      return plain[1];
    }
  }
  return fallback;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function rewriteWikilink(text, fromName, toName) {
  if (!text || fromName === toName) return text;
  const from = escapeRegExp(fromName);
  const pattern = new RegExp(`(!?\\[\\[)${from}(?=([|#\\]]))`, "g");
  return text.replace(pattern, `$1${toName}`);
}

function extractWikilinks(text) {
  const links = [];
  const pattern = /!?\[\[([^\[\]\n]+)\]\]/g;
  let match = pattern.exec(text);
  while (match) {
    const target = match[1].split("|")[0].split("#")[0].trim();
    if (target) links.push(target.replace(/\.md$/i, "").trim());
    match = pattern.exec(text);
  }
  return links;
}

class GenerationError extends Error {
  constructor(message, phase = "generation") {
    super(message);
    this.name = "GenerationError";
    this.phase = phase;
  }
}

class AIEduModal extends Modal {
  constructor(plugin) {
    super(plugin.app);
    this.plugin = plugin;
    this.jobId = null;
    this.tutorial = null;
    this.markdown = null;
    this.savedPath = null;
    this.pausedGoalId = null;
    this.recommendation = "";
    this.planDraft = "";
    this.extraContent = null;
    this.cheatsheetContent = null;
    this.busy = false;
    this.touched = false;
    this.completed = false;
    this.closed = false;
    this.lastForm = null;
    this.brokenLinks = [];
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    this.modalEl.addClass("ai-edu-modal");
    this.modalEl.addClass("ai-edu-modal-wide");
    this.titleEl.setText("创建并生成教程");
    contentEl.createEl("p", {
      cls: "ai-edu-subtitle",
      text: "默认一次生成：价值判断、学习计划、验收标准和教程自动完成",
    });
    this.closeHintEl = contentEl.createEl("p", { cls: "ai-edu-draft-status" });

    const form = contentEl.createDiv("ai-edu-form");

    // 目标名称
    const titleField = this.createField(form, "目标名称 *");
    this.titleInputEl = titleField.createEl("input", {
      type: "text",
      cls: "ai-edu-input",
      attr: { placeholder: "例如：掌握命令行管道与重定向" },
    });
    this.titleInputEl.value = "";

    // 学科 / 领域
    const domainField = this.createField(form, "学科 / 领域");
    this.domainEl = domainField.createEl("select", { cls: "ai-edu-input" });
    DOMAINS.forEach((domain) => {
      this.domainEl.createEl("option", { value: domain.key, text: domain.label });
    });
    this.domainEl.value = "cs_it";

    // 为什么要学
    const motivationField = this.createField(form, "为什么要学");
    this.motivationEl = motivationField.createEl("textarea", {
      cls: "ai-edu-input",
      attr: { rows: "2", placeholder: "它和你的当前需求或长期目标有什么关系？" },
    });
    this.motivationEl.value = "";

    // 学完能做什么
    const applicationField = this.createField(form, "学完能做什么");
    this.applicationEl = applicationField.createEl("textarea", {
      cls: "ai-edu-input",
      attr: { rows: "2", placeholder: "尽量描述一个可观察、可验收的任务。" },
    });
    this.applicationEl.value = "";

    // 当前基础
    const levelField = this.createField(form, "当前基础");
    this.currentLevelEl = levelField.createEl("textarea", {
      cls: "ai-edu-input",
      attr: { rows: "2", placeholder: "你已经会什么、卡在哪里？" },
    });
    this.currentLevelEl.value = "";

    // 可投入总时间
    const timeField = this.createField(form, "可投入总时间");
    this.timeBudgetEl = timeField.createEl("input", {
      type: "text",
      cls: "ai-edu-input",
      attr: { placeholder: "共 10 小时" },
    });
    this.timeBudgetEl.value = "共 10 小时";
    timeField.createEl("span", {
      cls: "ai-edu-hint",
      text: "填总时长（如「共 10 小时」），不用拆成每天的时间安排",
    });

    // 能力层级
    const capabilityField = this.createField(form, "能力层级");
    this.capabilityEl = capabilityField.createEl("select", { cls: "ai-edu-input" });
    CAPABILITY_LEVELS.forEach((level) => {
      this.capabilityEl.createEl("option", {
        value: level.key,
        text: `${level.key} · ${level.name}`,
      });
    });
    this.capabilityEl.value = "L2";
    this.capabilityHintEl = capabilityField.createEl("span", { cls: "ai-edu-hint" });

    // 生成挡位
    const tierField = this.createField(form, "生成挡位");
    this.tierEl = tierField.createEl("select", { cls: "ai-edu-input" });
    GENERATION_TIERS.forEach((tier) => {
      this.tierEl.createEl("option", {
        value: tier.key,
        text: `${tier.name} · ${tier.key}`,
      });
    });
    this.tierEl.value = this.plugin.settings.generationTier || "standard";
    this.tierHintEl = tierField.createEl("span", { cls: "ai-edu-hint" });

    // 额外练习文件
    const extraField = this.createField(form, "额外练习文件");
    const extraLabel = extraField.createEl("label", { cls: "ai-edu-check" });
    this.extraEl = extraLabel.createEl("input", { type: "checkbox" });
    extraLabel.createEl("span", {
      text: "生成独立的额外练习文件（含参考答案，与教程内必要练习分开）",
    });
    this.extraEl.checked = false;
    extraField.createEl("span", {
      cls: "ai-edu-hint",
      text: "开启后会随教程生成一份 Markdown 练习集并在教程中建立双链；教程内的必要练习不受影响",
    });

    this.statusEl = contentEl.createDiv("ai-edu-status");
    this.statusEl.setText("需要先启动本地 AI Edu 后端（默认 http://127.0.0.1:8000）。");

    const actions = contentEl.createDiv("ai-edu-actions");
    this.submitEl = actions.createEl("button", { text: "创建并生成教程", cls: "mod-cta" });
    this.createOnlyEl = actions.createEl("button", { text: "仅创建目标" });
    const cancel = actions.createEl("button", { text: "取消" });

    this.submitEl.addEventListener("click", () => this.submit());
    this.createOnlyEl.addEventListener("click", () => this.createOnly());
    cancel.addEventListener("click", () => this.close());

    // 单行输入框里按 Enter、或任意位置按 Ctrl/Cmd+Enter 直接提交，避免长表单必须滚到底部
    contentEl.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const target = event.target;
      const isTextInput =
        target && target.tagName === "INPUT" && (target.type || "text") === "text";
      if (event.ctrlKey || event.metaKey || isTextInput) {
        event.preventDefault();
        this.submit();
      }
    });

    const updateHints = () => {
      const level = CAPABILITY_LEVELS.find((l) => l.key === this.capabilityEl.value);
      this.capabilityHintEl.setText(level ? level.description : "");
      const tier = GENERATION_TIERS.find((t) => t.key === this.tierEl.value);
      this.tierHintEl.setText(
        `${tier ? tier.description : ""} 一键生成会按此挡位自动完成价值判断、计划、验收标准与教程。`
      );
    };
    updateHints();

    const touch = () => {
      this.touched = true;
      updateHints();
    };
    [
      this.titleInputEl,
      this.domainEl,
      this.motivationEl,
      this.applicationEl,
      this.currentLevelEl,
      this.timeBudgetEl,
      this.capabilityEl,
      this.tierEl,
      this.extraEl,
    ].forEach((el) => {
      el.addEventListener("input", touch);
      el.addEventListener("change", touch);
    });

    this.closeHintEl.setText("关闭窗口会清空本次填写内容；生成成功后会自动打开新教程。");

    // 打开即聚焦第一个字段：键盘操作（Tab）可以按表单顺序走完
    window.setTimeout(() => this.titleInputEl && this.titleInputEl.focus(), 50);
  }

  createField(parent, labelText) {
    const wrap = parent.createDiv("ai-edu-field");
    wrap.createEl("label", { cls: "ai-edu-label", text: labelText });
    return wrap;
  }

  readForm() {
    return {
      title: this.titleInputEl.value.trim(),
      domain_key: this.domainEl.value,
      motivation: this.motivationEl.value.trim(),
      application_context: this.applicationEl.value.trim(),
      current_level: this.currentLevelEl.value.trim(),
      time_budget: this.timeBudgetEl.value.trim(),
      capability_level: this.capabilityEl.value,
      generate_extra_exercises: !!this.extraEl.checked,
      generation_tier: this.tierEl.value,
    };
  }

  buildRequirement(form) {
    return (
      [
        form.application_context,
        form.motivation,
        form.current_level ? `当前基础：${form.current_level}` : "",
        form.time_budget ? `可投入时间：${form.time_budget}` : "",
      ]
        .filter(Boolean)
        .join("\n") || form.title
    );
  }

  setBusy(busy) {
    this.busy = busy;
    this.submitEl.disabled = busy;
    this.createOnlyEl.disabled = busy;
    this.submitEl.setText(busy ? "自动生成中…" : "创建并生成教程");
  }

  async submit() {
    if (this.busy) return;
    const form = this.readForm();
    if (!form.title) {
      this.statusEl.setText("请填写目标名称。");
      this.titleInputEl.focus();
      return;
    }
    this.lastForm = form;
    this.plugin.settings.generationTier = form.generation_tier;
    await this.plugin.saveSettings();

    this.setBusy(true);
    this.statusEl.setText("正在提交生成任务…");
    this.removePausedPanel();
    try {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/goals/quickstart`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          requirement: this.buildRequirement(form),
        }),
      });
      const started = await readJson(response);
      if (response.status === 409 && started?.detail?.code === "generation_paused") {
        this.setBusy(false);
        this.showPausedOptions(started.detail);
        return;
      }
      if (response.status >= 300 || !started || !started.tutorial) {
        throw new GenerationError(requestErrorMessage(started, response));
      }
      this.tutorial = started.tutorial;
      this.jobId = started.job_id || null;
      if (this.jobId) {
        await this.pollJob();
      }
      this.statusEl.setText("教程已生成，正在获取 Markdown 与配套文件…");
      await this.loadAndDeliver();
    } catch (error) {
      this.setBusy(false);
      const phase = error instanceof GenerationError ? error.phase : "generation";
      const prefix = phase === "delivery" ? "交付失败" : "生成失败";
      this.statusEl.setText(`${prefix}：${error.message}`);
      if (phase === "delivery" && this.markdown && this.tutorial) {
        this.showRetryDelivery();
      }
    }
  }

  async createOnly() {
    if (this.busy) return;
    const form = this.readForm();
    if (!form.title) {
      this.statusEl.setText("请填写目标名称。");
      this.titleInputEl.focus();
      return;
    }
    this.lastForm = form;
    this.plugin.settings.generationTier = form.generation_tier;
    await this.plugin.saveSettings();

    this.setBusy(true);
    this.statusEl.setText("正在创建学习目标…");
    try {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/goals`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const goal = await readJson(response);
      if (response.status >= 300 || !goal) {
        throw new GenerationError(requestErrorMessage(goal, response));
      }
      this.completed = true;
      this.clearDraft();
      if (!this.closed) this.close();
      new Notice(`已创建学习目标：${goal.title}`, 5000);
    } catch (error) {
      this.statusEl.setText(`创建失败：${error.message}`);
      this.setBusy(false);
    }
  }

  showPausedOptions(detail) {
    this.pausedGoalId = detail.goal_id;
    this.recommendation =
      detail.recommendation || detail.message || "AI 判断当前需求不值得继续。";
    this.planDraft = this.applicationEl.value.trim() || this.titleInputEl.value.trim();
    this.statusEl.setText("AI 已暂停生成，请选择继续方式。");

    this.removePausedPanel();
    const panel = this.contentEl.createDiv("ai-edu-paused");
    panel.createEl("div", { cls: "ai-edu-status", text: this.recommendation });

    const buttons = panel.createDiv("ai-edu-actions");
    const proceed = buttons.createEl("button", { text: "坚决执行", cls: "mod-cta" });
    const adopt = buttons.createEl("button", {
      text: "采纳AI建议后立即执行",
      cls: "mod-cta",
    });
    const revise = buttons.createEl("button", { text: "修改计划" });

    const editorArea = panel.createDiv("ai-edu-form");
    editorArea.style.display = "none";
    const planArea = editorArea.createDiv("ai-edu-field");
    this.planEl = planArea.createEl("textarea", {
      cls: "ai-edu-input",
      attr: { rows: "4" },
    });
    this.planEl.value = this.planDraft;
    const saveArea = editorArea.createDiv("ai-edu-actions");
    const save = saveArea.createEl("button", { text: "保存修改并执行", cls: "mod-cta" });

    proceed.addEventListener("click", () => this.resumePaused("proceed"));
    adopt.addEventListener("click", () => this.resumePaused("adopt"));
    revise.addEventListener("click", () => {
      editorArea.style.display = editorArea.style.display === "none" ? "" : "none";
      if (editorArea.style.display === "") this.planEl.focus();
    });
    save.addEventListener("click", () => this.reviseAndRun(this.planEl.value));
  }

  removePausedPanel() {
    const existing = this.contentEl.querySelector(".ai-edu-paused");
    if (existing) existing.remove();
  }

  async resumePaused(action) {
    if (!this.pausedGoalId) return;
    this.setBusy(true);
    this.statusEl.setText(action === "adopt" ? "正在采纳 AI 建议并生成…" : "正在坚决执行并生成…");
    try {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/goals/${this.pausedGoalId}/tutorials/quickstart`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pause_action: action }),
      });
      const result = await readJson(response);
      if (response.status >= 300 || !result || !result.tutorial) {
        throw new GenerationError(requestErrorMessage(result, response));
      }
      this.tutorial = result.tutorial;
      this.jobId = result.job_id || null;
      if (this.jobId) await this.pollJob();
      this.statusEl.setText("教程已生成，正在获取 Markdown 与配套文件…");
      await this.loadAndDeliver();
    } catch (error) {
      this.setBusy(false);
      this.statusEl.setText(`续跑失败：${error.message}`);
    }
  }

  async reviseAndRun(plan) {
    const revised = String(plan || "").trim();
    if (!revised || !this.pausedGoalId) return;
    this.setBusy(true);
    this.statusEl.setText("正在保存修改后的计划…");
    try {
      await requestUrl({
        url: `${this.plugin.apiBase()}/api/goals/${this.pausedGoalId}`,
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ application_context: revised, user_notes: revised }),
      });
      await this.resumePaused("proceed");
    } catch (error) {
      this.setBusy(false);
      this.statusEl.setText(`修改计划失败：${error.message}`);
    }
  }

  async pollJob() {
    for (let tick = 0; tick < 600; tick++) {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/generation-jobs/${this.jobId}`,
        method: "GET",
      });
      const job = await readJson(response);
      if (response.status >= 300 || !job) {
        throw new GenerationError(requestErrorMessage(job, response));
      }
      this.statusEl.setText(`正在生成教程：${job.progress || 0}% — ${job.stage || job.status}`);
      if (job.status === "done") return;
      if (job.status === "failed") {
        throw new GenerationError(job.error_message || job.error_code || "后台生成任务失败");
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new GenerationError("生成超时。请稍后在 AI Edu 中查看任务状态。");
  }

  async fetchExport(path, fallbackName) {
    const response = await requestUrl({ url: `${this.plugin.apiBase()}${path}`, method: "GET" });
    if (response.status >= 300) {
      throw new GenerationError(`获取 ${fallbackName || "Markdown"} 失败：HTTP ${response.status}`, "delivery");
    }
    return {
      name: safeName(fileNameFromResponse(response, fallbackName)),
      content: response.text,
    };
  }

  async loadAndDeliver() {
    if (!this.tutorial) throw new GenerationError("没有可交付的教程");
    const tutorialResponse = await requestUrl({
      url: `${this.plugin.apiBase()}/api/tutorials/${this.tutorial.id}`,
      method: "GET",
    });
    const tutorial = await readJson(tutorialResponse);
    if (tutorialResponse.status >= 300 || !tutorial) {
      throw new GenerationError(requestErrorMessage(tutorial, tutorialResponse), "delivery");
    }
    const content = (tutorial.current_version && tutorial.current_version.content) || {};
    const sections = content.sections || [];
    if (!sections.length) {
      throw new GenerationError("教程任务已结束，但当前版本没有章节内容", "delivery");
    }
    this.tutorial = tutorial;

    const baseTitle =
      (this.lastForm && this.lastForm.title) || tutorial.title || "AI Edu 教程";
    const main = await this.fetchExport(
      `/api/tutorials/${this.tutorial.id}/export`,
      `${baseTitle}-教程`
    );
    this.markdown = main.content;
    this.savedPath = null;
    this.cheatsheetContent = null;
    this.extraContent = null;

    const files = [main];
    if (content.cheatsheet && (content.cheatsheet.sections || []).length) {
      const cheat = await this.fetchExport(
        `/api/tutorials/${this.tutorial.id}/export/cheatsheet`,
        content.cheatsheet.filename || `${baseTitle}-知识速查`
      );
      this.cheatsheetContent = cheat.content;
      files.push(cheat);
    }
    if (content.extra_exercises && (content.extra_exercises.exercises || []).length) {
      const extra = await this.fetchExport(
        `/api/tutorials/${this.tutorial.id}/export/exercises`,
        content.extra_exercises.filename || `${baseTitle}-额外练习`
      );
      this.extraContent = extra.content;
      files.push(extra);
    }

    await this.saveTutorialSet(files, main.name);
    await this.markDelivery();

    const savedPath = this.savedPath;
    this.completed = true;
    this.clearDraft();
    if (!this.closed) this.close();
    await this.openTutorialFile(savedPath);
    if (this.brokenLinks.length) {
      new Notice(
        `教程已打开，但有 ${this.brokenLinks.length} 个双链未解析：${this.brokenLinks
          .slice(0, 3)
          .join("、")}`,
        8000
      );
    } else {
      new Notice(`已生成并打开：${savedPath}`, 5000);
    }
  }

  async openTutorialFile(path) {
    if (!path) return;
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!file) return;
    const leaf = this.app.workspace.getLeaf("tab");
    await leaf.openFile(file);
    this.app.workspace.revealLeaf(leaf);
    try {
      this.app.workspace.setActiveLeaf(leaf, { focus: true });
    } catch (_) {
      try {
        this.app.workspace.setActiveLeaf(leaf, false, true);
      } catch (__) {
        /* 旧版本没有焦点参数时，openFile 已把新标签设为当前 */
      }
    }
  }

  async saveTutorialSet(files, mainName) {
    await this.plugin.ensureFolder(this.plugin.settings.folder);

    // 全部文件使用同一后缀，避免主教程与配套文件重名后互相断链
    let suffix = "";
    for (let counter = 2; counter < 100; counter += 1) {
      const paths = files.map((file) =>
        this.vaultPath(`${safeName(file.name)}${suffix}.md`)
      );
      if (paths.every((path) => !this.app.vault.getAbstractFileByPath(path))) break;
      suffix = ` v${counter}`;
    }

    const renamed = files.map((file) => ({
      original: safeName(file.name),
      final: `${safeName(file.name)}${suffix}`,
      content: file.content,
    }));

    // 重名时同步改写所有文件里的双链，保证 [[...]] 仍指向实际写入的文件
    renamed.forEach((file) => {
      renamed.forEach((other) => {
        if (file.original !== other.final) {
          file.content = rewriteWikilink(file.content, other.original, other.final);
        }
      });
    });

    const saved = [];
    for (const file of renamed) {
      const path = this.vaultPath(`${file.final}.md`);
      await this.app.vault.create(path, file.content);
      saved.push({ path, name: file.final });
    }

    const main = saved.find((entry) => entry.name === `${mainName}${suffix}`) || saved[0];
    this.savedPath = main.path;
    this.savedCount = saved.length;
    this.brokenLinks = this.validateWikilinks(renamed);
  }

  vaultPath(fileName) {
    const folder = String(this.plugin.settings.folder || "").trim();
    return normalizePath(folder ? `${folder}/${fileName}` : fileName);
  }

  validateWikilinks(files) {
    const known = new Set(files.map((file) => file.final));
    this.app.vault.getMarkdownFiles().forEach((f) => known.add(f.basename));
    const broken = [];
    files.forEach((file) => {
      extractWikilinks(file.content).forEach((target) => {
        const base = target.split("/").pop();
        if (!known.has(base)) broken.push(target);
      });
    });
    return Array.from(new Set(broken));
  }

  async markDelivery() {
    if (!this.tutorial || !this.savedPath) return;
    try {
      await requestUrl({
        url: `${this.plugin.apiBase()}/api/tutorials/${this.tutorial.id}/delivery`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: "delivered",
          path: this.savedPath,
          version: (this.tutorial.current_version && this.tutorial.current_version.version) || 0,
        }),
      });
    } catch (_) {
      new Notice("笔记已写入 Vault，但交付状态回写失败。", 6000);
    }
  }

  showRetryDelivery() {
    const existing = this.contentEl.querySelector(".ai-edu-retry");
    if (existing) existing.remove();
    const actions = this.contentEl.createDiv("ai-edu-actions ai-edu-retry");
    const retry = actions.createEl("button", { text: "重试交付", cls: "mod-cta" });
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      this.statusEl.setText("正在重试交付…");
      try {
        await this.loadAndDeliver();
      } catch (error) {
        retry.disabled = false;
        this.statusEl.setText(`交付失败：${error.message}`);
      }
    });
  }

  clearDraft() {
    if (Object.prototype.hasOwnProperty.call(this.plugin.settings, "draft")) {
      delete this.plugin.settings.draft;
      this.plugin.saveSettings().catch(() => {});
    }
  }

  onClose() {
    this.closed = true;
    this.clearDraft();
    if (!this.completed && this.touched) {
      new Notice(
        this.busy
          ? "已清空本次填写内容；后台生成任务仍在继续"
          : "已清空本次填写内容",
        4000
      );
    }
    this.contentEl.empty();
  }
}

class AIEduSettingTab extends PluginSettingTab {
  constructor(plugin) {
    super(plugin.app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "AI Edu Tutorial Delivery" });

    new Setting(containerEl)
      .setName("API base URL")
      .setDesc("本地 AI Edu FastAPI 服务地址，不要填第三方代理。")
      .addText((text) =>
        text
          .setPlaceholder("http://127.0.0.1:8000")
          .setValue(this.plugin.settings.apiBaseUrl)
          .onChange(async (value) => {
            this.plugin.settings.apiBaseUrl = value.trim().replace(/\/+$/, "");
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Vault folder")
      .setDesc("教程与配套文件（知识速查 / 额外练习）的保存目录；不存在时会自动创建。")
      .addText((text) =>
        text
          .setPlaceholder("学习")
          .setValue(this.plugin.settings.folder)
          .onChange(async (value) => {
            this.plugin.settings.folder = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Default generation tier")
      .addDropdown((dropdown) =>
        dropdown
          .addOption("fast", "快速")
          .addOption("standard", "标准")
          .addOption("deep", "深度")
          .setValue(this.plugin.settings.generationTier)
          .onChange(async (value) => {
            this.plugin.settings.generationTier = value;
            await this.plugin.saveSettings();
          })
      );
  }
}

module.exports = class AIEduPlugin extends Plugin {
  async onload() {
    await this.loadSettings();
    this.addRibbonIcon("book-open", "AI Edu 教程", () => {
      new AIEduModal(this).open();
    });
    this.addCommand({
      id: "generate-and-save-tutorial",
      name: "生成并保存教程",
      callback: () => {
        new AIEduModal(this).open();
      },
    });
    this.addSettingTab(new AIEduSettingTab(this));
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    // 旧版本把草稿写在 data.json 里；现在关闭窗口即清空，加载时顺手清理历史草稿
    if (Object.prototype.hasOwnProperty.call(this.settings, "draft")) {
      delete this.settings.draft;
      await this.saveData(this.settings);
    }
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  apiBase() {
    return String(this.settings.apiBaseUrl || "").trim().replace(/\/+$/, "");
  }

  async ensureFolder(folder) {
    const normalized = normalizePath(folder || "");
    if (!normalized || normalized === "/") return;
    let current = "";
    for (const segment of normalized.split("/").filter(Boolean)) {
      current = current ? `${current}/${segment}` : segment;
      const existing = this.app.vault.getAbstractFileByPath(current);
      if (!existing) {
        await this.app.vault.createFolder(current);
      } else if (!existing.children) {
        throw new Error(`Vault 路径被同名文件占用：${current}`);
      }
    }
  }
};
