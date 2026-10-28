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
 * 7. 材料预校验规则与后端一致（扩展名 / 大小 / 空文件）。
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

const stub = {
  Plugin,
  PluginSettingTab,
  Setting,
  Modal,
  Notice,
  normalizePath,
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
    "module.exports.__MATERIAL_FALLBACK_LIMITS = MATERIAL_FALLBACK_LIMITS;",
    "module.exports.__buildMultipartBody = buildMultipartBody;",
  ].join("\n"),
  "utf8"
);
const pluginModule = require(tempFile);
const AIEduModal = pluginModule.__AIEduModal;
const validateMaterialFile = pluginModule.__validateMaterialFile;
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
      assert.strictEqual(options.body, "{}", "quickstart 请求体应为空对象");
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
