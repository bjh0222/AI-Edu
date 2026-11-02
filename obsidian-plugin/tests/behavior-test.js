"use strict";

/**
 * 插件行为测试（不依赖 Obsidian 运行时）：
 *   node tests/behavior-test.js
 *
 * 覆盖：
 * 1. 生成成功后的顺序：写文件 → 回写交付 → 关闭弹窗 → 打开新教程；
 * 2. 关闭弹窗（未完成且填过内容）：清空草稿并提示；
 * 3. 生成成功后的 onClose 不再重复提示；
 * 4. openTutorialFile 在当前窗口新标签打开并聚焦；
 * 5. 带参考材料的两步提交：建目标 → 上传材料 → 触发生成；
 * 6. 材料上传失败：不重复创建目标，重试只补传材料；
 * 7. 材料预校验规则与后端一致（扩展名 / 大小 / 空文件）；
 * 8. 「教程规范」一栏：分组下拉、规范正文预览、与网站一致的 id 映射；
 * 9. 手机端（安卓）适配：移动端 leaf 策略、回环地址告警、后端连通性自检。
 */

const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");
const assert = require("assert");

const notices = [];
const calls = [];

class Plugin {}
class PluginSettingTab {}
class Setting {
  setName() { return this; }
  setDesc() { return this; }
  setPlaceholder() { return this; }
  setValue() { return this; }
  addText() { return this; }
  addDropdown() { return this; }
  onChange() { return this; }
}
class Modal {
  constructor(app) { this.app = app; }
  open() {}
  close() {}
}
class Notice {
  constructor(message) { notices.push(String(message)); }
}
function normalizePath(value) {
  return String(value).replace(/\\/g, "/").replace(/\/+/g, "/");
}
let requestUrlImpl = async () => {
  throw new Error("requestUrl 不应在网络测试中被调用");
};
function requestUrl(...args) {
  return requestUrlImpl(...args);
}
// Platform 是可切换的：桌面与手机端的分支（leaf 策略 / 软键盘 / 回环告警）都要能测到
const Platform = { isMobile: false, isAndroidApp: false, isIosApp: false };

const stub = {
  Plugin,
  PluginSettingTab,
  Setting,
  Modal,
  Notice,
  normalizePath,
  Platform,
  requestUrl,
};
stub.setRequestUrl = (impl) => { requestUrlImpl = impl; };
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "obsidian") return stub;
  return originalLoad.call(this, request, parent, isMain);
};

// 把内部的 AIEduModal 暴露出来以便测试（只在临时副本里追加一行）
const source = fs.readFileSync(path.join(__dirname, "..", "ai-edu-tutorial-delivery", "main.js"), "utf8");
const tempFile = path.join(os.tmpdir(), `ai-edu-main-${process.pid}.js`);
fs.writeFileSync(
  tempFile,
  [
    source,
    "module.exports.__AIEduModal = AIEduModal;",
    "module.exports.__validateMaterialFile = validateMaterialFile;",
    "module.exports.__groupSpecs = groupSpecs;",
    "module.exports.__specGroupLabel = specGroupLabel;",
    "module.exports.__specPreviewMarkdown = specPreviewMarkdown;",
    "module.exports.__loopbackHostWarning = loopbackHostWarning;",
    "module.exports.__MATERIAL_FALLBACK_LIMITS = MATERIAL_FALLBACK_LIMITS;",
    "module.exports.__buildMultipartBody = buildMultipartBody;",
  ].join("\n"),
  "utf8"
);
const pluginModule = require(tempFile);
const AIEduModal = pluginModule.__AIEduModal;
const validateMaterialFile = pluginModule.__validateMaterialFile;
const groupSpecs = pluginModule.__groupSpecs;
const specGroupLabel = pluginModule.__specGroupLabel;
const specPreviewMarkdown = pluginModule.__specPreviewMarkdown;
const loopbackHostWarning = pluginModule.__loopbackHostWarning;
const MATERIAL_FALLBACK_LIMITS = pluginModule.__MATERIAL_FALLBACK_LIMITS;
const buildMultipartBody = pluginModule.__buildMultipartBody;
assert(AIEduModal, "应能拿到 AIEduModal");

function makeModal() {
  const modal = Object.create(AIEduModal.prototype);
  modal.plugin = {
    settings: { apiBaseUrl: "http://127.0.0.1:8000", folder: "学习", draft: { title: "旧内容" } },
    apiBase: () => "http://127.0.0.1:8000",
    saveSettings: async () => { calls.push("saveSettings"); },
  };
  modal.app = {
    vault: { getAbstractFileByPath: () => ({ path: "学习/测试-教程.md" }) },
    workspace: {
      getLeaf: (mode) => {
        calls.push(`getLeaf:${mode}`);
        return { openFile: async () => { calls.push("openFile"); } };
      },
      revealLeaf: () => { calls.push("revealLeaf"); },
      setActiveLeaf: () => { calls.push("setActiveLeaf"); },
    },
  };
  modal.contentEl = { empty: () => { calls.push("empty"); } };
  modal.statusEl = { setText: (text) => { modal.lastStatus = String(text); } };
  modal.submitEl = { disabled: false, setText: () => {} };
  modal.createOnlyEl = { disabled: false };
  modal.tutorial = { id: "t1", current_version: { version: 1, content: { sections: [{}] } } };
  modal.lastForm = { title: "测试" };
  modal.closed = false;
  modal.busy = false;
  modal.touched = false;
  modal.completed = false;
  return modal;
}

(async () => {
  // 1. 成功路径：顺序必须是 保存 → 交付 → 关闭 → 打开
  const success = makeModal();
  success.fetchExport = async (pathname, fallback) => ({ name: fallback, content: "[[测试-知识速查]]" });
  success.saveTutorialSet = async () => {
    calls.push("save");
    success.savedPath = "学习/测试-教程.md";
    success.brokenLinks = [];
  };
  success.markDelivery = async () => { calls.push("markDelivery"); };
  success.close = () => { calls.push("close"); success.closed = true; };
  success.openTutorialFile = async (target) => { calls.push(`open:${target}`); };

  const tutorialJson = success.tutorial;
  stub.setRequestUrl(async () => ({ status: 200, json: tutorialJson }));
  await success.loadAndDeliver();

  const order = calls.filter((item) => ["save", "markDelivery", "close", "open:学习/测试-教程.md"].includes(item));
  assert.deepStrictEqual(
    order,
    ["save", "markDelivery", "close", "open:学习/测试-教程.md"],
    `成功路径顺序错误：${calls.join(" → ")}`
  );
  assert.strictEqual(success.completed, true, "成功后应标记 completed");
  assert(!("draft" in success.plugin.settings), "成功后应清空草稿");
  assert(notices.some((text) => text.includes("已生成并打开")), "成功后应提示已打开教程");

  // 2. 关闭未完成的弹窗：清空 + 提示
  const closed = makeModal();
  closed.touched = true;
  const beforeClose = notices.length;
  AIEduModal.prototype.onClose.call(closed);
  assert(!("draft" in closed.plugin.settings), "关闭后应清空草稿");
  assert(notices.length > beforeClose, "关闭后应提示");
  assert(notices[notices.length - 1].includes("已清空本次填写内容"), "提示文案不符");

  // 3. 成功后的 onClose：不重复提示
  const done = makeModal();
  done.touched = true;
  done.completed = true;
  const beforeDone = notices.length;
  AIEduModal.prototype.onClose.call(done);
  assert.strictEqual(notices.length, beforeDone, "成功后关闭不应再提示清空");

  // 4. 打开教程：当前窗口新标签 + 聚焦
  calls.length = 0;
  const opener = makeModal();
  await AIEduModal.prototype.openTutorialFile.call(opener, "学习/测试-教程.md");
  assert.deepStrictEqual(
    calls.filter((item) => item.startsWith("getLeaf") || item === "openFile" || item === "revealLeaf" || item === "setActiveLeaf"),
    ["getLeaf:tab", "openFile", "revealLeaf", "setActiveLeaf"],
    `打开教程的调用顺序错误：${calls.join(" → ")}`
  );

  // 5. 带参考材料的两步提交：建目标 → 上传材料 → 触发生成 → 交付
  function makeFile(name, size) {
    return {
      name,
      size,
      type: "text/plain",
      arrayBuffer: async () => new ArrayBuffer(8),
    };
  }

  function makeMaterial(name, kind) {
    return {
      key: `k-${name}`,
      file: makeFile(name, 1024),
      kind,
      status: "pending",
      error: "",
    };
  }

  const baseForm = {
    title: "带材料的目标",
    domain_key: "cs_it",
    motivation: "",
    application_context: "",
    current_level: "",
    hard_constraints: "",
    time_budget: "共 10 小时",
    capability_level: "L2",
    generate_extra_exercises: false,
    generation_tier: "standard",
  };

  calls.length = 0;
  notices.length = 0;
  const httpCalls = [];
  stub.setRequestUrl(async (options) => {
    httpCalls.push(`${options.method} ${options.url}`);
    const url = options.url;
    if (options.method === "POST" && url.endsWith("/api/goals")) {
      return { status: 200, json: { id: "g1", title: "带材料的目标" } };
    }
    if (options.method === "POST" && url.endsWith("/materials")) {
      return { status: 200, json: { id: "m1", filename: "x" } };
    }
    if (options.method === "POST" && url.endsWith("/tutorials/quickstart")) {
      const body = JSON.parse(options.body);
      assert.strictEqual(
        Object.keys(body).length,
        1,
        `两步提交的 quickstart 只应带 format_spec_id：${options.body}`
      );
      assert.strictEqual(body.format_spec_id, null, "未选择规范时应传 null（自动匹配）");
      return { status: 200, json: { tutorial: { id: "t1" }, job_id: null } };
    }
    if (options.method === "GET" && url.endsWith("/api/tutorials/t1")) {
      return {
        status: 200,
        json: { id: "t1", title: "带材料的目标", current_version: { version: 1, content: { sections: [{}] } } },
      };
    }
    throw new Error(`unexpected request: ${options.method} ${url}`);
  });

  const twoStep = makeModal();
  twoStep.lastForm = baseForm;
  twoStep.pendingMaterials = [makeMaterial("讲义.pdf", "reference"), makeMaterial("例题.md", "example_source")];
  twoStep.fetchExport = async (p, fallback) => ({ name: fallback, content: "# t" });
  twoStep.saveTutorialSet = async () => {
    calls.push("save");
    twoStep.savedPath = "学习/带材料的目标-教程.md";
    twoStep.brokenLinks = [];
  };
  twoStep.markDelivery = async () => { calls.push("markDelivery"); };
  twoStep.close = () => { calls.push("close"); twoStep.closed = true; };
  twoStep.openTutorialFile = async () => { calls.push("open"); };

  await AIEduModal.prototype.submitWithMaterials.call(twoStep, twoStep.lastForm, true);
  assert.deepStrictEqual(
    httpCalls,
    [
      "POST http://127.0.0.1:8000/api/goals",
      "POST http://127.0.0.1:8000/api/goals/g1/materials",
      "POST http://127.0.0.1:8000/api/goals/g1/materials",
      "POST http://127.0.0.1:8000/api/goals/g1/tutorials/quickstart",
      "GET http://127.0.0.1:8000/api/tutorials/t1",
    ],
    `两步提交请求顺序错误：${httpCalls.join(" → ")}`
  );
  assert(twoStep.pendingMaterials.every((row) => row.status === "done"), "上传后所有材料应标记 done");
  assert.strictEqual(twoStep.createdGoal.id, "g1", "应记录已创建目标");
  assert.strictEqual(twoStep.completed, true, "成功后应标记 completed");
  assert.deepStrictEqual(
    calls.filter((item) => ["save", "markDelivery", "close", "open"].includes(item)),
    ["save", "markDelivery", "close", "open"],
    `交付顺序错误：${calls.join(" → ")}`
  );

  // 6. 材料上传失败：目标只创建一次；重试不重复建目标
  httpCalls.length = 0;
  let materialAttempts = 0;
  stub.setRequestUrl(async (options) => {
    httpCalls.push(`${options.method} ${options.url}`);
    const url = options.url;
    if (options.method === "POST" && url.endsWith("/api/goals")) {
      return { status: 200, json: { id: "g2", title: "失败重试" } };
    }
    if (options.method === "POST" && url.endsWith("/materials")) {
      materialAttempts += 1;
      return { status: 400, json: { detail: { code: "bad_extension", message: "不支持的类型「exe」" } } };
    }
    throw new Error(`unexpected request: ${options.method} ${url}`);
  });

  const failCase = makeModal();
  failCase.lastForm = baseForm;
  failCase.pendingMaterials = [makeMaterial("坏文件.exe", "reference")];
  await AIEduModal.prototype.submitWithMaterials.call(failCase, failCase.lastForm, false);
  assert.strictEqual(failCase.createdGoal.id, "g2", "失败后应保留已创建目标");
  assert(failCase.lastStatus.includes("已创建但尚未生成"), `失败提示不符：${failCase.lastStatus}`);

  failCase.pendingMaterials = failCase.pendingMaterials.map((row) =>
    row.status === "error" ? { ...row, file: makeFile("换成md.md", 512), status: "pending", error: "" } : row
  );
  stub.setRequestUrl(async (options) => {
    httpCalls.push(`${options.method} ${options.url}`);
    const url = options.url;
    if (options.method === "POST" && url.endsWith("/api/goals")) {
      throw new Error("不应重复创建目标");
    }
    if (options.method === "POST" && url.endsWith("/materials")) {
      materialAttempts += 1;
      return { status: 200, json: { id: "m2" } };
    }
    throw new Error(`unexpected request: ${options.method} ${url}`);
  });
  await AIEduModal.prototype.submitWithMaterials.call(failCase, failCase.lastForm, false);
  assert.strictEqual(failCase.createdGoal.id, "g2", "重试后目标不应变化");
  assert.strictEqual(failCase.completed, true, "补传成功后应完成");
  assert.strictEqual(
    httpCalls.filter((item) => item.endsWith("/api/goals")).length,
    1,
    `POST /api/goals 应只出现一次：${httpCalls.join(" → ")}`
  );
  assert.strictEqual(materialAttempts, 2, "重试只应补传一次材料");

  // 7. 暂停分支：quickstart 返回 409 generation_paused 时交给暂停面板，且目标已带材料
  httpCalls.length = 0;
  stub.setRequestUrl(async (options) => {
    httpCalls.push(`${options.method} ${options.url}`);
    const url = options.url;
    if (options.method === "POST" && url.endsWith("/api/goals")) {
      return { status: 200, json: { id: "g3", title: "暂停用例" } };
    }
    if (options.method === "POST" && url.endsWith("/materials")) {
      return { status: 200, json: { id: "m3" } };
    }
    if (options.method === "POST" && url.endsWith("/tutorials/quickstart")) {
      return {
        status: 409,
        json: {
          detail: {
            code: "generation_paused",
            message: "AI 判断当前需求不值得继续",
            goal_id: "g3",
            recommendation: "先明确目标",
          },
        },
      };
    }
    throw new Error(`unexpected request: ${options.method} ${url}`);
  });
  const pausedCase = makeModal();
  pausedCase.lastForm = baseForm;
  pausedCase.pendingMaterials = [makeMaterial("讲义.pdf", "reference")];
  let pausedDetail = null;
  pausedCase.showPausedOptions = (detail) => { pausedDetail = detail; };
  await AIEduModal.prototype.submitWithMaterials.call(pausedCase, pausedCase.lastForm, true);
  assert(pausedDetail && pausedDetail.goal_id === "g3", "应进入暂停面板并带上目标 id");
  assert.strictEqual(pausedCase.busy, false, "暂停后应解除 busy");
  assert(httpCalls.some((item) => item.endsWith("/api/goals/g3/materials")), "暂停前材料应已上传");


  // 8. 格式规范选择：readForm 映射与网站一致（auto→null / ""→"" / id→id）
  function makeFormModal(specValue) {
    const modal = makeModal();
    modal.titleInputEl = { value: " 线性代数练习 " };
    modal.domainEl = { value: "math_logic" };
    modal.motivationEl = { value: "动机" };
    modal.applicationEl = { value: "应用" };
    modal.currentLevelEl = { value: "基础" };
    modal.hardConstraintsEl = { value: "约束" };
    modal.timeBudgetEl = { value: "无上限" };
    modal.capabilityEl = { value: "L3" };
    modal.extraEl = { checked: false };
    modal.tierEl = { value: "standard" };
    modal.formatSpecEl = { value: specValue };
    return modal;
  }

  const autoForm = AIEduModal.prototype.readForm.call(makeFormModal("auto"));
  assert.strictEqual(autoForm.format_spec_id, null, "auto 应映射为 null");
  const noneForm = AIEduModal.prototype.readForm.call(makeFormModal(""));
  assert.strictEqual(noneForm.format_spec_id, "", "「本次不使用」应映射为空串");
  const manualForm = AIEduModal.prototype.readForm.call(makeFormModal("spec-42"));
  assert.strictEqual(manualForm.format_spec_id, "spec-42", "手动选择应原样提交 id");

  // 9. 规范下拉渲染：已删除的已存规范回落到自动匹配；存在的保持选中
  // 假 select：顶层 createEl 收到 option 或 optgroup；optgroup 再挂自己的 option。
  // 扁平 options 列表保留「渲染顺序」，groups 记录分组标签，两者都要能断言。
  function makeFakeSelect() {
    const self = {
      options: [],
      groups: [],
      value: "",
      empty() { self.options = []; self.groups = []; },
      createEl(tag, opts) {
        if (tag === "optgroup") {
          self.groups.push(opts.attr && opts.attr.label);
          return {
            createEl(_childTag, childOpts) {
              self.options.push(childOpts);
            },
          };
        }
        self.options.push(opts);
        return null;
      },
    };
    return self;
  }

  const specModal = makeModal();
  specModal.formatSpecs = [
    { id: "s1", name: "练习生成规范", scene: "exercise", is_default: false, version: 26 },
    { id: "s2", name: "知识性教程规范", scene: "default_tutorial", is_default: true, version: 4 },
    { id: "s3", name: "实践性教程规范", scene: "practical_tutorial", is_default: false, version: 2 },
    { id: "s4", name: "试卷生成规范", scene: "exam_paper", is_default: false, version: 11 },
    { id: "s5", name: "我的自定义规范", scene: "my_custom", is_default: false, version: 1 },
  ];
  specModal.formatSpecEl = makeFakeSelect();
  specModal.formatSpecId = "s-deleted";
  AIEduModal.prototype.renderFormatSpecOptions.call(specModal);
  assert.deepStrictEqual(
    specModal.formatSpecEl.options.map((o) => o.value),
    ["auto", "", "s2", "s3", "s1", "s4", "s5"],
    `下拉应按「教程 → 练习与试卷 → 其他」分组排序：${JSON.stringify(specModal.formatSpecEl.options)}`
  );
  assert.deepStrictEqual(
    specModal.formatSpecEl.groups,
    ["教程规范", "练习与试卷规范", "其他规范"],
    `分组标签错误：${JSON.stringify(specModal.formatSpecEl.groups)}`
  );
  assert(specModal.formatSpecEl.options.some((o) => o.text.includes("· 默认")), "默认规范应标注");
  assert.strictEqual(specModal.formatSpecEl.value, "auto", "已删除的规范应回落自动匹配");
  assert.strictEqual(specModal.formatSpecId, "auto", "回落应同步回写当前选择");

  specModal.formatSpecId = "s1";
  AIEduModal.prototype.renderFormatSpecOptions.call(specModal);
  assert.strictEqual(specModal.formatSpecEl.value, "s1", "仍存在的已存规范应保持选中");

  // 10. 暂停续跑携带格式规范选择
  httpCalls.length = 0;
  const bodies = [];
  stub.setRequestUrl(async (options) => {
    httpCalls.push(`${options.method} ${options.url}`);
    const url = options.url;
    if (options.method === "POST" && url.endsWith("/tutorials/quickstart")) {
      bodies.push(options.body);
      return { status: 200, json: { tutorial: { id: "t9" }, job_id: null } };
    }
    throw new Error(`unexpected request: ${options.method} ${url}`);
  });
  const resumeModal = makeModal();
  resumeModal.pausedGoalId = "g9";
  resumeModal.formatSpecEl = { value: "spec-7" };
  resumeModal.loadAndDeliver = async () => { calls.push("deliver"); };
  await AIEduModal.prototype.resumePaused.call(resumeModal, "proceed");
  const resumeBody = JSON.parse(bodies[0]);
  assert.strictEqual(resumeBody.pause_action, "proceed", "续跑应带 pause_action");
  assert.strictEqual(resumeBody.format_spec_id, "spec-7", "续跑应带格式规范选择");

  // 11. 手机端（安卓）适配：leaf 策略 / 回环地址告警 / 后端连通性自检 / 规范正文预览
  // 11a. 桌面端仍是 getLeaf("tab")（回归：不能被移动端分支改掉）
  calls.length = 0;
  Platform.isMobile = false;
  const desktopOpener = makeModal();
  await AIEduModal.prototype.openTutorialFile.call(desktopOpener, "学习/测试-教程.md");
  assert(calls.includes("getLeaf:tab"), `桌面端应使用 getLeaf("tab")：${calls.join(" → ")}`);

  // 11b. 手机端改用 getLeaf(true)：移动端没有标签页概念
  calls.length = 0;
  Platform.isMobile = true;
  const mobileOpener = makeModal();
  await AIEduModal.prototype.openTutorialFile.call(mobileOpener, "学习/测试-教程.md");
  assert(calls.includes("getLeaf:true"), `手机端应使用 getLeaf(true)：${calls.join(" → ")}`);
  assert.deepStrictEqual(
    calls.filter((item) => ["openFile", "revealLeaf", "setActiveLeaf"].includes(item)),
    ["openFile", "revealLeaf", "setActiveLeaf"],
    `手机端打开顺序错误：${calls.join(" → ")}`
  );

  // 11c. getLeaf 抛错（移动端某些版本）时退回当前叶子，主路径不能断
  calls.length = 0;
  const fallbackOpener = makeModal();
  let fallbackCalls = 0;
  fallbackOpener.app.workspace.getLeaf = (mode) => {
    fallbackCalls += 1;
    calls.push(`getLeaf:${mode}`);
    if (fallbackCalls === 1) throw new Error("mobile: tab not supported");
    return { openFile: async () => { calls.push("openFile"); } };
  };
  await AIEduModal.prototype.openTutorialFile.call(fallbackOpener, "学习/测试-教程.md");
  assert(calls.includes("openFile"), `getLeaf 抛错后应仍打开文件：${calls.join(" → ")}`);
  Platform.isMobile = false;

  // 11d. 回环地址告警：只在手机端出现，局域网 IP 不告警
  Platform.isMobile = true;
  assert(
    loopbackHostWarning("http://127.0.0.1:8000").includes("指向手机自己"),
    "手机端 127.0.0.1 应告警"
  );
  assert(loopbackHostWarning("http://localhost:8000").length > 0, "手机端 localhost 应告警");
  assert.strictEqual(loopbackHostWarning("http://192.168.1.20:8000"), "", "局域网 IP 不应告警");
  assert.strictEqual(loopbackHostWarning("http://[fd00::1]:8000"), "", "IPv6 局域网不应告警");
  Platform.isMobile = false;
  assert.strictEqual(loopbackHostWarning("http://127.0.0.1:8000"), "", "桌面端不需要该告警");

  // 11e. 连通性自检：成功写入状态行；失败给出手机端可执行排查步骤
  const probeOk = makeModal();
  stub.setRequestUrl(async (options) => {
    assert(options.url.endsWith("/api/health"), `自检应打 /api/health：${options.url}`);
    return { status: 200, json: { demo: false, llm_configured: true } };
  });
  const okResult = await AIEduModal.prototype.probeApi.call(probeOk);
  assert.strictEqual(okResult.ok, true, "健康检查应成功");
  assert(probeOk.lastStatus.includes("已连接"), `状态行应显示已连接：${probeOk.lastStatus}`);

  const probeFail = makeModal();
  stub.setRequestUrl(async () => { throw new Error("Failed to connect"); });
  Platform.isMobile = true;
  const failResult = await AIEduModal.prototype.probeApi.call(probeFail);
  assert.strictEqual(failResult.ok, false, "连不上时应标记失败");
  assert(probeFail.lastStatus.includes("Failed to connect"), `应带原始原因：${probeFail.lastStatus}`);
  assert(probeFail.lastStatus.includes("防火墙"), `手机端应给出排查步骤：${probeFail.lastStatus}`);
  Platform.isMobile = false;

  // 11f. 规范正文预览：段落顺序与网页端 previewMarkdown 一致，空字段跳过
  const previewText = specPreviewMarkdown({
    name: "知识性教程规范",
    description: "面向零基础读者的知识性教程",
    version: 4,
    scene: "default_tutorial",
    applicable_tasks: "概念解释、原理学习",
    trigger_keywords: ["原理", "推导"],
    excluded_keywords: [],
    output_goal: "输出一份系统、准确的教程",
    content_structure: "# 教程名称\n\n- 第一章是「教程概览」",
    format_rules: "",
    required_rules: "- 概念必须有定义",
    reference_examples: "",
    deliverables: [],
  });
  const headings = previewText.split("\n").filter((line) => line.startsWith("## "));
  assert.deepStrictEqual(
    headings,
    ["## 匹配与适用", "## 输出目标与受众", "## 交付物（一个交付物一章）", "## 内容结构", "## 必须遵守"],
    `预览段落顺序错误：${JSON.stringify(headings)}`
  );
  assert(previewText.startsWith("# 知识性教程规范"), "预览应以规范名为一级标题");
  assert(!previewText.includes("## 格式与表达"), "空字段应整段跳过，不留空标题");
  assert(previewText.includes("- 概念必须有定义"), "必须遵守的规则应出现在预览里");
  assert(previewText.includes("未配置结构化交付物"), "无交付物时应说明由大纲模型决定");

  // 11g. 分组与族别标签：阅读教程规范单独点名（后端对它走两阶段生成）
  assert.strictEqual(
    specGroupLabel({ name: "阅读教程规范", scene: "reading_guide" }),
    "阅读教程规范",
    "阅读规范应单独点名"
  );
  assert.strictEqual(specGroupLabel({ scene: "practical_tutorial" }), "教程规范", "实践性属教程族");
  assert.strictEqual(specGroupLabel({ scene: "exam_paper" }), "练习与试卷规范", "试卷属练习与试卷族");
  assert.strictEqual(specGroupLabel({ scene: "whatever" }), "其他规范", "未知 scene 落到其他规范");
  const grouped = groupSpecs([
    { id: "a", scene: "default_tutorial" },
    { id: "b", scene: "exercise" },
    { id: "c", scene: "reading_guide" },
  ]);
  assert.deepStrictEqual(
    grouped.map((g) => [g.label, g.specs.map((s) => s.id)]),
    [["教程规范", ["a", "c"]], ["练习与试卷规范", ["b"]]],
    `分组结果错误：${JSON.stringify(grouped)}`
  );
  assert.deepStrictEqual(groupSpecs([]), [], "空列表不应产出空分组");

  // 8. 材料预校验与 multipart 构造
  assert.strictEqual(validateMaterialFile(makeFile("a.md", 10), MATERIAL_FALLBACK_LIMITS), "", "md 应通过");
  assert(validateMaterialFile(makeFile("a.exe", 10), MATERIAL_FALLBACK_LIMITS).includes("不支持的类型"), "exe 应被拒");
  assert(
    validateMaterialFile(makeFile("a.md", 21 * 1024 * 1024), MATERIAL_FALLBACK_LIMITS).includes("文件过大"),
    "超限应被拒"
  );
  assert.strictEqual(validateMaterialFile(makeFile("a.md", 0), MATERIAL_FALLBACK_LIMITS), "文件为空", "空文件应被拒");
  const multipart = await buildMultipartBody(makeFile("讲义.pdf", 8), "reference");
  const multipartText = Buffer.from(multipart.body).toString("utf8");
  assert(multipart.contentType.startsWith("multipart/form-data; boundary="), "应返回 multipart Content-Type");
  assert(multipartText.includes('name="kind"\r\n\r\nreference'), "应包含 kind 字段");
  assert(multipartText.includes("filename*=UTF-8''"), "应包含 RFC 2231 文件名");
  assert(multipartText.includes(`filename*=UTF-8''${encodeURIComponent("讲义.pdf")}`), "文件名应按 UTF-8 编码保留原文");

  fs.unlinkSync(tempFile);
  console.log("behavior-test passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
