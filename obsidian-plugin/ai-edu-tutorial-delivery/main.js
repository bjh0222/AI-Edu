"use strict";

const {
  Plugin,
  PluginSettingTab,
  Setting,
  Modal,
  Notice,
  Platform,
  normalizePath,
  requestUrl,
} = require("obsidian");

const DEFAULT_SETTINGS = {
  apiBaseUrl: "http://127.0.0.1:8000",
  folder: "学习",
  generationTier: "standard",
  // 格式规范选择：auto 自动匹配；"" 本次不使用特殊规范；其他值为手动选定 spec id
  formatSpecId: "auto",
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

// 与 services/api/app/services/materials.py 的 ALLOWED_EXTENSIONS / KIND_LABELS 保持一致；
// 后端 /api/materials/limits 不可达时作为上传校验的兜底
const MATERIAL_FALLBACK_LIMITS = {
  max_bytes: 20 * 1024 * 1024,
  allowed_extensions: [
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
  ],
  kinds: [
    { key: "reference", label: "参考资料" },
    { key: "example_source", label: "例题来源" },
  ],
};

// 规范分组：与后端 services/api/app/services/utils.py 的 GUIDANCE_SCENES（教程族）、
// format_specs.py 的 READING_GUIDE_SCENE / exercise / exam_paper 保持一致。
// 分组只是「选规范时不误选另一族」的界面便利；后端匹配仍只看 scene 与规范 id，
// 所以下面新增 scene 时必须同步后端，否则新规范会掉进「其他规范」。
const SPEC_GROUPS = [
  {
    key: "tutorial",
    label: "教程规范",
    scenes: ["default_tutorial", "knowledge_tutorial", "practical_tutorial", "reading_guide"],
  },
  { key: "paper", label: "练习与试卷规范", scenes: ["exercise", "exam_paper"] },
  { key: "other", label: "其他规范", scenes: [] },
];

const SPEC_DELIVERABLE_STATUS = {
  required: "必须",
  on_request: "用户要求时",
  optional: "可选",
  forbidden: "禁止",
};

function specScene(spec) {
  return String((spec && spec.scene) || "").trim();
}

function specGroupKey(spec) {
  const scene = specScene(spec);
  const hit = SPEC_GROUPS.find((group) => group.scenes.includes(scene));
  return hit ? hit.key : "other";
}

/** 规范族别标签：阅读教程规范单独点名（后端对它走两阶段生成，语义与教程族不同）。 */
function specGroupLabel(spec) {
  if (specScene(spec) === "reading_guide") return "阅读教程规范";
  const group = SPEC_GROUPS.find((item) => item.key === specGroupKey(spec));
  return group ? group.label : "其他规范";
}

/** 按分组整理规范列表；空组不出现，自定义 scene 落到「其他规范」。 */
function groupSpecs(specs) {
  return SPEC_GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    specs: (specs || []).filter((spec) => specGroupKey(spec) === group.key),
  })).filter((group) => group.specs.length > 0);
}

/**
 * 规范正文预览：段落顺序与 apps/web/lib/specs.ts 的 specPreviewMarkdown 完全一致，
 * 而后者又对齐 llm/prompts.py:_format_spec_block 的注入顺序 —— 这样插件里看到的层级
 * 就是网页预览的层级，也是生成时模型看到的层级。空字段整段跳过。
 */
function specPreviewMarkdown(spec) {
  const data = spec || {};
  const text = (value) => String(value == null ? "" : value).trim();
  const listText = (value) => (Array.isArray(value) ? value.map(text).filter(Boolean).join("、") : "");
  const deliverables = Array.isArray(data.deliverables) && data.deliverables.length
    ? data.deliverables
        .map((item) => `- ${text(item.name)}（${SPEC_DELIVERABLE_STATUS[item.status] || item.status || "可选"}）`)
        .join("\n")
    : "- 未配置结构化交付物（章节数与章名由大纲模型按知识逻辑决定）";
  const sections = [
    ["## 匹配与适用", [
      `适用任务：${text(data.applicable_tasks) || "未填写"}`,
      `适用意图：${listText(data.applicable_intents) || "未填写"}`,
      `排除场景：${listText(data.excluded_scenarios) || "无"}`,
      `排除意图：${listText(data.excluded_intents) || "无"}`,
      `触发关键词：${listText(data.trigger_keywords) || "未启用"}`,
      `排除关键词：${listText(data.excluded_keywords) || "无"}`,
    ]],
    ["## 输出目标与受众", [text(data.output_goal) || text(data.description) || "未填写",
      text(data.target_reader) ? `目标受众：${text(data.target_reader)}` : ""]],
    ["## 交付物（一个交付物一章）", [deliverables]],
    ["## 内容结构", [text(data.content_structure)]],
    ["## 参考示例", [text(data.reference_examples)]],
    ["## 格式与表达", [text(data.format_rules)]],
    ["## 必须遵守", [text(data.required_rules)]],
    ["## 建议遵守", [text(data.suggested_rules)]],
    ["## 可灵活调整", [text(data.flexible_rules)]],
    ["## 禁止出现", [text(data.forbidden_rules)]],
    ["## 验收标准", [text(data.acceptance_criteria)]],
    ["## 自定义补充规则", [text(data.custom_markdown)]],
  ];
  // 头部：描述为空时不留空行。正文里刻意的空行（如 content_structure 的分段）必须原样保留，
  // 所以这里不做全局折叠 —— 与 apps/web/lib/specs.ts 的 specPreviewMarkdown 保持一致。
  const description = text(data.description);
  const out = [`# ${text(data.name) || "未命名规范"}`];
  if (description) out.push("", description);
  out.push("");
  sections.forEach(([heading, lines]) => {
    const body = lines.map((line) => text(line)).filter(Boolean);
    if (!body.length) return;
    out.push(heading, ...body, "");
  });
  return out.join("\n").trimEnd();
}

/**
 * 手机端回环地址告警：127.0.0.1 / localhost 在安卓上指向手机自己，
 * 是「插件连不上后端」的头号原因。桌面端不需要这条提示。
 */
function loopbackHostWarning(baseUrl) {
  if (!Platform.isMobile) return "";
  const host = String(baseUrl || "")
    .replace(/^https?:\/\//i, "")
    .split("/")[0]
    .split(":")[0]
    .replace(/^\[|\]$/g, "");
  const loopback = ["127.0.0.1", "localhost", "0.0.0.0", "::1", ""];
  if (!loopback.includes(host.toLowerCase())) return "";
  return (
    `当前 API 地址是「${baseUrl || "未填写"}」。手机上 127.0.0.1 / localhost 指向手机自己，` +
    "连不到电脑上的 AI Edu。请在插件设置里改成电脑的局域网地址（例如 http://192.168.1.20:8000）：" +
    "电脑与手机连同一个 Wi-Fi，后端以 --host 0.0.0.0 启动（仓库的「启动 AI Edu.cmd」加 -Mobile 参数即可），" +
    "并在电脑防火墙放行 8000 端口。"
  );
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function materialExtensionsText(limits) {
  return (limits.allowed_extensions || []).map((ext) => String(ext).replace(".", "")).join(" / ");
}

// 与后端 save_upload 同规则的客户端预校验；返回错误文案，空串表示通过。
function validateMaterialFile(file, limits) {
  const name = String(file.name || "");
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  if (!(limits.allowed_extensions || []).includes(ext)) {
    return `不支持的类型「${ext || "无扩展名"}」，仅支持 ${materialExtensionsText(limits)}`;
  }
  if (file.size > limits.max_bytes) {
    return `文件过大（${formatSize(file.size)}），单文件上限 ${formatSize(limits.max_bytes)}`;
  }
  if (file.size === 0) return "文件为空";
  return "";
}

/**
 * 手工构造 multipart/form-data（Obsidian 的 requestUrl 只接受字符串 / ArrayBuffer，
 * 不支持 FormData）。文件名同时给出 ASCII 兜底和 RFC 2231 的 filename*，保证中文名不乱码。
 */
async function buildMultipartBody(file, kind) {
  const boundary = `----AIEduBoundary${Date.now().toString(36)}${Math.random()
    .toString(36)
    .slice(2, 10)}`;
  const encoder = new TextEncoder();
  const asciiName = String(file.name || "upload")
    .replace(/[^\x20-\x7E]/g, "_")
    .replace(/["\\]/g, "_");
  const contentType = /^[!-~]+$/.test(file.type || "") ? file.type : "application/octet-stream";
  const head = encoder.encode(
    `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="kind"\r\n\r\n${kind}\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="${asciiName}"; filename*=UTF-8''${encodeURIComponent(
        file.name
      )}\r\n` +
      `Content-Type: ${contentType}\r\n\r\n`
  );
  const tail = encoder.encode(`\r\n--${boundary}--\r\n`);
  const fileBytes = new Uint8Array(await file.arrayBuffer());
  const body = new Uint8Array(head.length + fileBytes.length + tail.length);
  body.set(head, 0);
  body.set(fileBytes, head.length);
  body.set(tail, head.length + fileBytes.length);
  return { body: body.buffer, contentType: `multipart/form-data; boundary=${boundary}` };
}

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

/**
 * 去掉不应参与双链校验的片段：围栏代码块、行内代码、数学环境（$...$ / $$...$$）。
 * 数学里的 [[...]] 是合法记号（形式幂级数环 R[[x]]、矩阵 [[a,b],[c,d]]），不是双链。
 */
function stripProtectedSpans(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`[^`\n]*`/g, "")
    .replace(/\$\$[\s\S]*?\$\$/g, "")
    .replace(/\$[^$\n]+\$/g, "");
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
    // 暂存式「参考资料 / 例题来源」：目标创建成功后才真正上传
    this.pendingMaterials = [];
    this.materialLimits = MATERIAL_FALLBACK_LIMITS;
    // 格式规范候选（打开弹窗时后台拉取）与当前选择（默认沿用插件设置）
    this.formatSpecs = [];
    this.formatSpecId = plugin.settings.formatSpecId || "auto";
    // 「教程规范」一栏的展开态与后端连通性自检结果
    this.specPreviewOpen = false;
    this.apiProbe = null;
    this.materialKind = "reference";
    this.createdGoal = null;
    this.materialMessage = "";
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

    // 硬性约束：注入所有生成阶段 prompt，违反任一条即视为交付不合格
    const constraintsField = this.createField(form, "硬性约束（可选）");
    this.hardConstraintsEl = constraintsField.createEl("textarea", {
      cls: "ai-edu-input",
      attr: {
        rows: "2",
        placeholder:
          "生成内容必须满足的强制要求，每行一条。例如：\n不安排任何日程\n所有命令示例同时给出 Linux 与 Windows 写法",
      },
    });
    this.hardConstraintsEl.value = "";
    constraintsField.createEl("span", {
      cls: "ai-edu-hint",
      text: "填写后会注入价值判断、计划、验收标准、教程与配套文件的全部生成提示词；违反任一条即视为交付不合格",
    });

    // 教程规范：与网站创建页同语义（自动匹配 / 本次不使用 / 手动选择），
    // 但下拉按「教程规范 / 练习与试卷规范 / 其他规范」分组，并且能就地展开规范正文
    // —— 手机上看不到网页端的「偏好设置 → 格式规范」，展开是唯一确认途径。
    this.createSpecField(form);
    this.loadFormatSpecs();

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

    // 参考资料 / 例题来源（可选）：暂存式上传区
    this.createMaterialsSection(form);
    void this.loadMaterialLimits();

    this.statusEl = contentEl.createDiv("ai-edu-status");
    this.statusEl.setText(this.initialStatusText());
    void this.probeApi();

    const actions = contentEl.createDiv("ai-edu-actions");
    this.submitEl = actions.createEl("button", { text: "创建并生成教程", cls: "mod-cta" });
    this.createOnlyEl = actions.createEl("button", { text: "仅创建目标" });
    const cancel = actions.createEl("button", { text: "取消" });

    this.submitEl.addEventListener("click", () => this.submit());
    this.createOnlyEl.addEventListener("click", () => this.createOnly());
    cancel.addEventListener("click", () => this.close());

    // 桌面端：单行输入框里按 Enter、或任意位置按 Ctrl/Cmd+Enter 直接提交，
    // 避免长表单必须滚到底部。手机端只认 Ctrl/Cmd+Enter（软键盘的「回车/前往」
    // 是输入习惯键，一按就提交会误启动一次几分钟的生成，代价太高）。
    contentEl.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const target = event.target;
      const isTextInput =
        target && target.tagName === "INPUT" && (target.type || "text") === "text";
      const chordSubmit = event.ctrlKey || event.metaKey;
      if (chordSubmit || (isTextInput && !Platform.isMobile)) {
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
      this.hardConstraintsEl,
      this.formatSpecEl,
      this.timeBudgetEl,
      this.capabilityEl,
      this.tierEl,
      this.extraEl,
    ].forEach((el) => {
      el.addEventListener("input", touch);
      el.addEventListener("change", touch);
    });

    this.closeHintEl.setText("关闭窗口会清空本次填写内容；生成成功后会自动打开新教程。");

    // 桌面端打开即聚焦第一个字段：键盘操作（Tab）可以按表单顺序走完。
    // 手机端刻意不聚焦 —— 一打开就弹软键盘会把整张表单盖住，用户还得先手动收起。
    if (!Platform.isMobile) {
      window.setTimeout(() => this.titleInputEl && this.titleInputEl.focus(), 50);
    }
  }

  /**
   * 「教程规范」一栏：下拉（分组）+ 展开正文 + 当前规范的族别提示。
   * 选择语义与网站创建页逐字一致，只是多了分组和就地查看。
   */
  createSpecField(form) {
    const field = this.createField(form, "教程规范");
    const row = field.createDiv("ai-edu-spec-row");
    this.formatSpecEl = row.createEl("select", {
      cls: "ai-edu-input ai-edu-spec-select",
      attr: { "aria-label": "教程规范" },
    });
    const toggle = row.createEl("button", {
      cls: "ai-edu-spec-toggle",
      text: "查看规范",
      attr: { type: "button", "aria-expanded": "false" },
    });
    toggle.addEventListener("click", () => {
      this.specPreviewOpen = !this.specPreviewOpen;
      this.renderSpecPreview();
    });

    this.specMetaEl = field.createEl("span", { cls: "ai-edu-hint" });
    this.specPreviewEl = field.createDiv("ai-edu-spec-preview");
    this.specPreviewEl.style.display = "none";
    this.renderFormatSpecOptions();

    this.formatSpecEl.addEventListener("change", () => {
      this.formatSpecId = this.formatSpecEl.value;
      // 换规范时保持展开态并刷新正文，用户才能立刻对比两份规范的差别
      this.renderSpecPreview();
    });
    return field;
  }

  /** 当前选中的规范对象；auto / 不使用 / 已删除时返回 null。 */
  selectedSpec() {
    const value = this.formatSpecEl ? this.formatSpecEl.value : this.formatSpecId || "auto";
    if (!value || value === "auto") return null;
    return this.formatSpecs.find((spec) => spec.id === value) || null;
  }

  renderSpecPreview() {
    if (!this.specPreviewEl || !this.specMetaEl) return;
    const spec = this.selectedSpec();
    const value = this.formatSpecEl ? this.formatSpecEl.value : this.formatSpecId || "auto";
    const toggle = this.specPreviewEl.parentElement
      ? this.specPreviewEl.parentElement.querySelector(".ai-edu-spec-toggle")
      : null;

    if (!spec) {
      this.specMetaEl.setText(
        value === "auto"
          ? "自动匹配：按需求文本的关键词与语义挑选规范，未命中时使用默认规范；手动选择优先于自动匹配。"
          : "本次不使用特殊规范：正文只受「硬性约束」与通用排版要求约束。"
      );
      this.specPreviewEl.empty();
      this.specPreviewEl.style.display = "none";
      if (toggle) {
        toggle.disabled = true;
        toggle.setText("查看规范");
        toggle.setAttribute("aria-expanded", "false");
      }
      return;
    }

    if (toggle) toggle.disabled = false;
    this.specMetaEl.setText(
      `${specGroupLabel(spec)} · v${spec.version || 1}${spec.is_default ? " · 默认规范" : ""}` +
        `${spec.is_builtin ? " · 内置" : ""}｜手动选择优先于自动匹配；规范会在大纲生成前冻结为本任务快照。`
    );
    if (!this.specPreviewOpen) {
      this.specPreviewEl.empty();
      this.specPreviewEl.style.display = "none";
      if (toggle) {
        toggle.setText("查看规范");
        toggle.setAttribute("aria-expanded", "false");
      }
      return;
    }
    this.specPreviewEl.empty();
    this.specPreviewEl.style.display = "";
    if (toggle) {
      toggle.setText("收起规范");
      toggle.setAttribute("aria-expanded", "true");
    }
    this.specPreviewEl.createEl("pre", { cls: "ai-edu-spec-pre", text: specPreviewMarkdown(spec) });
    this.specPreviewEl.createEl("div", {
      cls: "ai-edu-hint",
      text: "以上为规范全文预览，段落顺序与生成时注入提示词的顺序一致。修改请到网页端「偏好设置 → 格式规范」。",
    });
  }

  initialStatusText() {
    const warning = loopbackHostWarning(this.plugin.apiBase());
    if (warning) return warning;
    return Platform.isMobile
      ? `手机端需与电脑同一局域网，API 地址填电脑的局域网 IP（当前：${this.plugin.apiBase() || "未设置"}）。`
      : "需要先启动本地 AI Edu 后端（默认 http://127.0.0.1:8000）。";
  }

  /**
   * 打开弹窗即自检后端连通性（GET /api/health），把「静默连不上」变成一句可执行的诊断。
   * 手机端最常见的失败是 API 地址填了 127.0.0.1、后端只监听 127.0.0.1、或防火墙没放行。
   * 自检失败绝不阻断填表：自动匹配在后端不可达时仍会回落，用户可以先把表填完。
   */
  async probeApi() {
    const base = this.plugin.apiBase();
    if (!base) {
      this.apiProbe = { ok: false, reason: "no_base" };
      return this.apiProbe;
    }
    try {
      const response = await requestUrl({ url: `${base}/api/health`, method: "GET" });
      const data = await readJson(response);
      if (response.status >= 300) throw new Error(requestErrorMessage(data, response));
      this.apiProbe = { ok: true, demo: !!(data && data.demo) };
      if (!this.busy && this.statusEl) {
        this.statusEl.setText(
          `已连接 AI Edu 后端：${base}${data && data.demo ? "（演示模式，未配置模型）" : ""}`
        );
      }
    } catch (error) {
      this.apiProbe = {
        ok: false,
        reason: error && error.message ? error.message : String(error),
      };
      if (!this.busy && this.statusEl) {
        this.statusEl.setText(this.probeFailureText(this.apiProbe.reason));
      }
    }
    return this.apiProbe;
  }

  probeFailureText(reason) {
    const base = this.plugin.apiBase() || "（未设置）";
    const lines = [`连不上 AI Edu 后端 ${base}：${reason}`];
    if (Platform.isMobile) {
      lines.push(
        "手机端排查顺序：① 电脑与手机连同一个 Wi-Fi；② API 地址改成电脑的局域网 IP（127.0.0.1 在手机上指向手机自己）；" +
          "③ 后端以 --host 0.0.0.0 启动（「启动 AI Edu.cmd -Mobile」）；④ 电脑防火墙放行 8000 端口。"
      );
    } else {
      lines.push("请先启动后端：cd services/api; .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000");
    }
    return lines.join("\n");
  }

  createField(parent, labelText) {
    const wrap = parent.createDiv("ai-edu-field");
    wrap.createEl("label", { cls: "ai-edu-label", text: labelText });
    return wrap;
  }

  createMaterialsSection(parent) {
    const field = this.createField(parent, "参考资料 / 例题来源（可选）");
    this.materialsBoxEl = field.createDiv("ai-edu-materials");
    this.renderMaterialsSection();
  }

  renderMaterialsSection() {
    const box = this.materialsBoxEl;
    if (!box) return;
    const limits = this.materialLimits || MATERIAL_FALLBACK_LIMITS;
    box.empty();

    const head = box.createDiv("ai-edu-materials-head");
    head.createEl("span", { cls: "ai-edu-materials-caption", text: "上传分类" });
    const kindGroup = head.createDiv("ai-edu-kind-group");
    kindGroup.setAttribute("role", "radiogroup");
    kindGroup.setAttribute("aria-label", "材料分类");
    limits.kinds.forEach((item) => {
      const active = item.key === this.materialKind;
      const btn = kindGroup.createEl("button", {
        cls: `ai-edu-kind-btn${active ? " is-active" : ""}`,
        text: item.label,
        attr: { type: "button", role: "radio", "aria-checked": active ? "true" : "false" },
      });
      btn.addEventListener("click", () => {
        if (this.busy || this.materialKind === item.key) return;
        this.materialKind = item.key;
        this.renderMaterialsSection();
      });
    });

    const pick = head.createEl("button", {
      cls: "ai-edu-material-pick",
      text: "选择文件（可多选）",
      attr: { type: "button" },
    });
    this.materialPickEl = pick;
    pick.disabled = this.busy;
    pick.addEventListener("click", () => {
      if (!this.busy && this.materialInputEl) this.materialInputEl.click();
    });

    const input = box.createEl("input", {
      cls: "ai-edu-material-input",
      attr: {
        type: "file",
        multiple: "multiple",
        accept: limits.allowed_extensions.join(","),
        "aria-label": "选择参考资料或例题来源文件",
      },
    });
    this.materialInputEl = input;
    input.addEventListener("change", () => {
      if (input.files && input.files.length) this.addPendingMaterials(Array.from(input.files));
      input.value = "";
    });

    box.createEl("div", {
      cls: "ai-edu-hint",
      text: `支持 ${materialExtensionsText(limits)}；单文件上限 ${formatSize(limits.max_bytes)}；提交时先创建学习目标，再把这些文件上传到该目标并注入生成依据。`,
    });

    this.materialMessageEl = box.createDiv("ai-edu-material-message");
    if (this.materialMessage) this.materialMessageEl.setText(this.materialMessage);
    else this.materialMessageEl.style.display = "none";

    this.materialListEl = box.createDiv("ai-edu-material-list");
    this.renderMaterialList();

    box.createEl("p", {
      cls: "ai-edu-hint",
      text: "文件先暂存在本地，点击下方按钮提交时才上传；关闭弹窗会丢弃这些文件。",
    });
  }

  renderMaterialList() {
    if (!this.materialListEl) return;
    this.materialListEl.empty();
    this.pendingMaterials.forEach((row) => this.renderMaterialRow(row));
  }

  renderMaterialRow(row) {
    const limits = this.materialLimits || MATERIAL_FALLBACK_LIMITS;
    const kind = limits.kinds.find((item) => item.key === row.kind);
    const item = this.materialListEl.createDiv("ai-edu-material-row");
    const line = item.createDiv("ai-edu-material-line");
    line.createEl("span", {
      cls: "ai-edu-material-kind",
      text: (kind && kind.label) || row.kind,
    });
    line.createEl("span", {
      cls: "ai-edu-material-name",
      text: row.file.name,
      attr: { title: row.file.name },
    });
    line.createEl("span", { cls: "ai-edu-material-size", text: formatSize(row.file.size) });
    line.createEl("span", {
      cls: `ai-edu-material-status is-${row.status}`,
      text:
        row.status === "uploading"
          ? "上传中…"
          : row.status === "done"
            ? "已上传"
            : row.status === "error"
              ? "失败"
              : "待上传",
    });
    const remove = line.createEl("button", {
      cls: "ai-edu-material-remove",
      text: "移除",
      attr: { type: "button" },
    });
    remove.disabled = this.busy || row.status === "uploading";
    remove.addEventListener("click", () => this.removePendingMaterial(row.key));
    if (row.status === "uploading") {
      item.createDiv("ai-edu-material-bar").createDiv("ai-edu-material-bar-fill");
    }
    if (row.status === "error" && row.error) {
      item.createDiv({ cls: "ai-edu-material-error", text: row.error });
    }
  }

  addPendingMaterials(files) {
    if (this.busy || !files.length) return;
    const limits = this.materialLimits || MATERIAL_FALLBACK_LIMITS;
    const rejected = [];
    files.forEach((file) => {
      const problem = validateMaterialFile(file, limits);
      if (problem) rejected.push(`${file.name}：${problem}`);
      else {
        this.pendingMaterials.push({
          key: `${Date.now()}-${this.pendingMaterials.length}-${file.name}`,
          file,
          kind: this.materialKind,
          status: "pending",
          error: "",
        });
      }
    });
    this.touched = true;
    this.materialMessage = rejected.join("；");
    this.renderMaterialList();
    if (this.materialMessageEl) {
      if (this.materialMessage) this.materialMessageEl.setText(this.materialMessage);
      else this.materialMessageEl.style.display = "none";
    }
  }

  removePendingMaterial(key) {
    if (this.busy) return;
    this.pendingMaterials = this.pendingMaterials.filter((row) => row.key !== key);
    this.renderMaterialList();
  }

  patchPendingMaterial(key, patch) {
    this.pendingMaterials = this.pendingMaterials.map((row) =>
      row.key === key ? { ...row, ...patch } : row
    );
    this.renderMaterialList();
  }

  /** 拉取上传限制（扩展名 / 单文件上限 / 分类），失败时保留内置默认值。 */
  async loadMaterialLimits() {
    try {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/materials/limits`,
        method: "GET",
      });
      const data = await readJson(response);
      if (
        response.status >= 300 ||
        !data ||
        !Array.isArray(data.allowed_extensions) ||
        !data.allowed_extensions.length
      ) {
        return;
      }
      const limits = {
        max_bytes: Number(data.max_bytes) > 0 ? Number(data.max_bytes) : MATERIAL_FALLBACK_LIMITS.max_bytes,
        allowed_extensions: data.allowed_extensions,
        kinds: Array.isArray(data.kinds) && data.kinds.length ? data.kinds : MATERIAL_FALLBACK_LIMITS.kinds,
      };
      if (JSON.stringify(limits) === JSON.stringify(this.materialLimits)) return;
      this.materialLimits = limits;
      this.renderMaterialsSection();
    } catch (_) {
      // 后端不可达时保留内置默认限制
    }
  }

  /** 逐个上传暂存材料：成功的行标记 done（重试时跳过），失败的保留错误信息并返回列表。 */
  async uploadPendingMaterials(goalId) {
    const failed = [];
    for (const row of this.pendingMaterials) {
      if (row.status === "done") continue;
      this.patchPendingMaterial(row.key, { status: "uploading", error: "" });
      try {
        const { body, contentType } = await buildMultipartBody(row.file, row.kind);
        const response = await requestUrl({
          url: `${this.plugin.apiBase()}/api/goals/${goalId}/materials`,
          method: "POST",
          headers: { "Content-Type": contentType },
          body,
        });
        const data = await readJson(response);
        if (response.status >= 300) {
          throw new Error(requestErrorMessage(data, response));
        }
        this.patchPendingMaterial(row.key, { status: "done", error: "" });
      } catch (error) {
        const message = error && error.message ? error.message : String(error);
        this.patchPendingMaterial(row.key, { status: "error", error: message });
        failed.push(`${row.file.name}：${message}`);
      }
    }
    return failed;
  }

  readForm() {
    return {
      title: this.titleInputEl.value.trim(),
      domain_key: this.domainEl.value,
      motivation: this.motivationEl.value.trim(),
      application_context: this.applicationEl.value.trim(),
      current_level: this.currentLevelEl.value.trim(),
      time_budget: this.timeBudgetEl.value.trim(),
      hard_constraints: this.hardConstraintsEl.value.trim(),
      capability_level: this.capabilityEl.value,
      generate_extra_exercises: !!this.extraEl.checked,
      generation_tier: this.tierEl.value,
      format_spec_id: this.formatSpecPayloadValue(),
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

  /**
   * 提交给后端的 format_spec_id：auto → null（自动匹配）；"" → 空串（不使用特殊规范）；
   * 其他值 → 手动选定的规范 id。与网站创建页的映射规则完全一致。
   */
  formatSpecPayloadValue() {
    const value = this.formatSpecEl ? this.formatSpecEl.value : this.formatSpecId || "auto";
    return value === "auto" ? null : value;
  }

  renderFormatSpecOptions() {
    if (!this.formatSpecEl) return;
    const previous = this.formatSpecId || "auto";
    this.formatSpecEl.empty();
    this.formatSpecEl.createEl("option", {
      value: "auto",
      text: "自动匹配（未命中时使用默认规范）",
    });
    this.formatSpecEl.createEl("option", { value: "", text: "本次不使用特殊规范" });
    // 分组只影响界面可读性：value 仍是规范 id，提交语义与网站创建页逐字一致
    groupSpecs(this.formatSpecs).forEach((group) => {
      const optgroup = this.formatSpecEl.createEl("optgroup", { attr: { label: group.label } });
      group.specs.forEach((spec) => {
        optgroup.createEl("option", {
          value: spec.id,
          text: `${spec.name}${spec.is_default ? " · 默认" : ""}`,
        });
      });
    });
    // 设置里记住的规范可能已被删除：失效时回落到自动匹配，避免提交一个不存在的 id
    const valid =
      previous === "auto" ||
      previous === "" ||
      this.formatSpecs.some((spec) => spec.id === previous);
    this.formatSpecEl.value = valid ? previous : "auto";
    this.formatSpecId = this.formatSpecEl.value;
    this.renderSpecPreview();
  }

  async loadFormatSpecs() {
    // 后台拉取规范列表；后端不可达时保留「自动匹配 / 本次不使用」两个兜底选项，不阻断填表
    try {
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/format-specs`,
        method: "GET",
      });
      const data = await readJson(response);
      if (response.status >= 300 || !Array.isArray(data)) return;
      this.formatSpecs = data;
      this.renderFormatSpecOptions();
    } catch (_) {
      /* 忽略：列表缺失不影响提交（后端仍会自动匹配） */
    }
  }

  setBusy(busy) {
    this.busy = busy;
    this.submitEl.disabled = busy;
    this.createOnlyEl.disabled = busy;
    this.submitEl.setText(busy ? "自动生成中…" : "创建并生成教程");
    if (this.materialPickEl) this.materialPickEl.disabled = busy;
    if (this.materialListEl) this.renderMaterialList();
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
    this.plugin.settings.formatSpecId = form.format_spec_id === null ? "auto" : form.format_spec_id;
    await this.plugin.saveSettings();

    // 带参考材料的提交流程：材料接口挂在目标下（/api/goals/{goal_id}/materials），
    // 所以先创建目标 → 上传材料 → 再触发生成，AI 才能把这些材料注入 prompt。
    if (this.pendingMaterials.length > 0) {
      await this.submitWithMaterials(form, true);
      return;
    }

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
    this.plugin.settings.formatSpecId = form.format_spec_id === null ? "auto" : form.format_spec_id;
    await this.plugin.saveSettings();

    if (this.pendingMaterials.length > 0) {
      await this.submitWithMaterials(form, false);
      return;
    }

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

  /**
   * 带参考材料的两步提交：
   * ① POST /api/goals 创建目标（失败不会误传材料）；
   * ② 逐个上传暂存材料到 /api/goals/{id}/materials；
   * ③ autoGenerate 时再 POST /api/goals/{id}/tutorials/quickstart 触发生成。
   * 上传失败时不重复建目标：已创建的目标记在 this.createdGoal，重试只补传材料。
   */
  async submitWithMaterials(form, autoGenerate) {
    const requirement = this.buildRequirement(form);
    this.setBusy(true);
    this.statusEl.setText(this.createdGoal ? "正在上传参考材料…" : "正在创建学习目标…");
    try {
      let goal = this.createdGoal;
      if (!goal) {
        const response = await requestUrl({
          url: `${this.plugin.apiBase()}/api/goals`,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            autoGenerate
              ? {
                  // 与后端 /api/goals/quickstart（create_and_quickstart）的字段处理保持一致
                  title: form.title,
                  domain_key: form.domain_key,
                  motivation: form.motivation || "完成用户提出的学习需求",
                  application_context: form.application_context || requirement,
                  current_level: form.current_level,
                  time_budget: form.time_budget,
                  hard_constraints: form.hard_constraints,
                  capability_level: form.capability_level,
                  generate_extra_exercises: form.generate_extra_exercises,
                  generation_tier: form.generation_tier,
                  user_notes: requirement,
                }
              : { ...form, user_notes: requirement }
          ),
        });
        goal = await readJson(response);
        if (response.status >= 300 || !goal) {
          throw new GenerationError(requestErrorMessage(goal, response));
        }
        this.createdGoal = goal;
      }

      const failed = await this.uploadPendingMaterials(goal.id);
      if (failed.length > 0) {
        this.setBusy(false);
        this.statusEl.setText(
          `材料上传失败：${failed.join("；")}。目标「${goal.title}」已创建但尚未生成；` +
            "可移除失败文件后重新提交，不会重复创建目标。"
        );
        return;
      }

      if (!autoGenerate) {
        this.completed = true;
        this.clearDraft();
        if (!this.closed) this.close();
        new Notice(`已创建学习目标：${goal.title}`, 5000);
        return;
      }

      this.statusEl.setText("参考材料已上传，正在提交生成任务…");
      const response = await requestUrl({
        url: `${this.plugin.apiBase()}/api/goals/${goal.id}/tutorials/quickstart`,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 两步提交里规范不能在建目标时绑定（GoalCreate 不接受该字段），
        // 与网站一致地在 quickstart 时传入：null 自动匹配 / "" 不使用 / id 手动
        body: JSON.stringify({ format_spec_id: form.format_spec_id ?? this.formatSpecPayloadValue() }),
      });
      const started = await readJson(response);
      if (response.status === 409 && started?.detail?.code === "generation_paused") {
        // 目标与材料都已就位，暂停面板里的续跑会复用同一个目标
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
        body: JSON.stringify({
          pause_action: action,
          format_spec_id: this.formatSpecPayloadValue(),
        }),
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
    // 手机端没有标签页概念（getLeaf("tab") 是桌面语义）：传 true 让 Obsidian
    // 自己决定在当前工作区新开一个叶子。getLeaf 也可能抛错（旧版 / 移动端权限），
    // 这时退回当前活动叶子，保证「教程能打开」这条主路径不断。
    let leaf;
    try {
      leaf = this.app.workspace.getLeaf(Platform.isMobile ? true : "tab");
    } catch (_) {
      leaf = this.app.workspace.getLeaf(false) || this.app.workspace.activeLeaf;
    }
    if (!leaf) return;
    await leaf.openFile(file);
    try {
      this.app.workspace.revealLeaf(leaf);
    } catch (_) {
      /* 移动端某些版本没有 revealLeaf：文件已打开，不影响结果 */
    }
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
      extractWikilinks(stripProtectedSpans(file.content)).forEach((target) => {
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

    if (Platform.isMobile) {
      new Setting(containerEl)
        .setName("手机端连接说明")
        .setDesc(
          "手机与电脑需在同一 Wi-Fi；API base URL 填电脑的局域网 IP（不是 127.0.0.1）。" +
            "后端要以 --host 0.0.0.0 启动（仓库根目录「启动 AI Edu.cmd -Mobile」），" +
            "并在电脑防火墙放行 8000 端口。网页端同理：手机浏览器打开 http://<电脑IP>:3001。" +
            "打开生成弹窗会自动自检连通性并把失败原因写进状态行。"
        );
    }

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
