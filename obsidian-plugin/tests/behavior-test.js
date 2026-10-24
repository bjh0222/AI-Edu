"use strict";

/**
 * 插件行为测试（不依赖 Obsidian 运行时）：
 *   node tests/behavior-test.js
 *
 * 覆盖：
 * 1. 生成成功后的顺序：写文件 → 回写交付 → 关闭弹窗 → 打开新教程；
 * 2. 关闭弹窗（未完成且填过内容）：清空草稿并提示；
 * 3. 生成成功后的 onClose 不再重复提示；
 * 4. openTutorialFile 在当前窗口新标签打开并聚焦。
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
fs.writeFileSync(tempFile, `${source}\nmodule.exports.__AIEduModal = AIEduModal;\n`, "utf8");
const pluginModule = require(tempFile);
const AIEduModal = pluginModule.__AIEduModal;
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

  fs.unlinkSync(tempFile);
  console.log("behavior-test passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
