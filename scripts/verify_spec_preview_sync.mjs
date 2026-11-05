#!/usr/bin/env node
// 验证 apps/web/lib/specs.ts 与 obsidian-plugin/.../main.js 的规范预览实现一致。
//
// 插件不能 import 前端代码，两份是手工同步的等价副本；这份脚本把 skill 里
// 「改任一份必须跑一致性校验」从散文指令变成可执行检查（2026-11-02 实测 4/4
// 一致靠的是人肉，现在每次改动后跑一次即可）。
//
// 对比三件事：
//   1. SPEC_GROUPS / SPEC_DELIVERABLE_STATUS 数据
//   2. specPreviewMarkdown 输出（前端必须用 stages:false —— 插件只复刻非编辑态）
//   3. groupSpecs / specGroupLabel 按 scene 的分组与标签
//
// 用法：仓库根 node scripts/verify_spec_preview_sync.mjs（exit 0 = 一致）

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");
const specsTs = path.join(repo, "apps", "web", "lib", "specs.ts");
const pluginJs = path.join(repo, "obsidian-plugin", "ai-edu-tutorial-delivery", "main.js");

// ---- 前端实现：specs.ts 只有可擦除的 TS 语法（type 别名 / 泛型 / import type），
// Node 24 原生类型剥离可以直接加载；import type 会被擦掉，所以 @/lib/types 别名不会解析。
const web = await import(new URL(`file:///${specsTs.replaceAll("\\", "/")}`).href);

// ---- 插件实现：main.js 顶部 import Obsidian，不能整文件加载。
// 规范预览的整段实现（SPEC_GROUPS 起、loopbackHostWarning 止）是自包含的纯函数，
// 截取后在 vm 沙箱里求值。若将来这段引用了区块外的标识符，这里会报
// 「xxx is not defined」——届时扩大截取范围即可。
const pluginSrc = readFileSync(pluginJs, "utf8");
const START = "const SPEC_GROUPS = [";
const END = "function loopbackHostWarning";
const start = pluginSrc.indexOf(START);
const end = pluginSrc.indexOf(END, start);
if (start < 0 || end < 0) {
  console.error(`无法在 main.js 中定位规范预览实现（start=${start} end=${end}）`);
  process.exit(2);
}
const chunk = pluginSrc.slice(start, end);
const plugin = vm.runInNewContext(
  chunk + "\n;({ SPEC_GROUPS, SPEC_DELIVERABLE_STATUS, specScene, specGroupKey, specGroupLabel, groupSpecs, specPreviewMarkdown })",
  {},
  { filename: "main.js#spec-preview" },
);

let failures = 0;
const fail = (msg) => { failures += 1; console.error(`MISMATCH ${msg}`); };

// ---- 1. 数据常量
for (const key of ["SPEC_GROUPS", "SPEC_DELIVERABLE_STATUS"]) {
  const a = JSON.stringify(web[key]);
  const b = JSON.stringify(plugin[key]);
  if (a !== b) {
    fail(`${key} 数据不一致`);
    console.error(`  specs.ts: ${a}`);
    console.error(`  main.js : ${b}`);
  }
}

// ---- 2. specPreviewMarkdown 输出
// fixtures 覆盖：全字段 / 空字段 / 交付物（含未知 status）/ scene 分支 / null。
// status 故意不用 "" / 0 / false —— 两者对该形态语义不同（前端 ?? vs 插件 ||），
// 且后端 _normalize_deliverables 会把 status 归一化到四值枚举，不会出现。
const fixtures = {
  "全字段规范": {
    name: "全字段", description: "一句话描述", scene: "default_tutorial",
    applicable_tasks: "生成试卷", applicable_intents: ["出题", "变式"],
    excluded_scenarios: ["口算"], excluded_intents: [],
    trigger_keywords: ["试卷"], excluded_keywords: ["答案"],
    output_goal: "产出三套卷", target_reader: "高三学生",
    deliverables: [
      { name: "简要分析", status: "required" },
      { name: "第一套卷", status: "required" },
      { name: "拓展", status: "optional" },
      { name: "未知状态", status: "mystery" },
    ],
    content_structure: "### 栏目\n#### 题型",
    reference_examples: "示例正文", format_rules: "用 Markdown",
    required_rules: "不要答案", suggested_rules: "可加提示",
    flexible_rules: "排版可调", forbidden_rules: "禁止日程",
    acceptance_criteria: "三套卷齐备", custom_markdown: "自定义补充",
  },
  "只有名称": { name: "最小规范" },
  "无名称": {},
  "null": null,
  "交付物为空数组": { name: "无交付物", deliverables: [] },
  "交付物缺 status": { name: "缺状态", deliverables: [{ name: "某交付物" }] },
  "教程族 scene": { name: "教程", scene: "practical_tutorial" },
  "阅读教程 scene": { name: "阅读教程", scene: "reading_guide" },
  "未知 scene": { name: "未知", scene: "mystery_scene" },
};

for (const [name, spec] of Object.entries(fixtures)) {
  const a = web.specPreviewMarkdown(spec, { stages: false });
  const b = plugin.specPreviewMarkdown(spec);
  if (a !== b) {
    fail(`specPreviewMarkdown(${name}) 输出不一致`);
    const lines = a.split("\n");
    for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
      if (a.split("\n")[i] !== b.split("\n")[i]) {
        console.error(`  行 ${i + 1}:`);
        console.error(`    specs.ts: ${JSON.stringify(a.split("\n")[i])}`);
        console.error(`    main.js : ${JSON.stringify(b.split("\n")[i])}`);
      }
    }
  }
}

// ---- 3. 分组与标签
const mixed = [
  { name: "a", scene: "default_tutorial" },
  { name: "b", scene: "exam_paper" },
  { name: "c", scene: "reading_guide" },
  { name: "d", scene: "mystery_scene" },
];
for (const [label, run] of [
  ["groupSpecs", (mod) => JSON.stringify(mod.groupSpecs(mixed))],
  ["specGroupLabel", (mod) => JSON.stringify(mixed.map((s) => mod.specGroupLabel(s)))],
  ["specGroupKey", (mod) => JSON.stringify(mixed.map((s) => mod.specGroupKey(s)))],
]) {
  const a = run(web);
  const b = run(plugin);
  if (a !== b) {
    fail(`${label} 不一致`);
    console.error(`  specs.ts: ${a}`);
    console.error(`  main.js : ${b}`);
  }
}

if (failures) {
  console.error(`\n${failures} 处不一致。两份实现必须逐字等价：改完任一份后同步另一份，再跑本脚本。`);
  process.exit(1);
}
console.log("spec preview sync OK（数据 / 预览输出 / 分组标签 全部一致）");
