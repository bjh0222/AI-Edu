import type { FormatSpec } from "@/lib/types";

/**
 * 规范分组与「规范正文预览」的唯一事实来源。
 *
 * 分组只影响界面可读性：value 仍是规范 id，提交语义（auto→null / ""→不使用 / id→手动）
 * 与后端 resolve_spec 完全无关，后端匹配只看 scene 与规范 id。
 * 所以新增 scene 时必须同步这里，否则新规范会掉进「其他规范」。
 *
 * scene 常量对应后端：
 * - 教程族：services/api/app/services/utils.py 的 GUIDANCE_SCENES
 * - 阅读教程：services/api/app/services/format_specs.py 的 READING_GUIDE_SCENE
 * - 练习 / 试卷：scene == "exercise" / "exam_paper"
 *
 * Obsidian 插件 obsidian-plugin/ai-edu-tutorial-delivery/main.js 里有一份等价实现
 * （插件不能 import 前端代码），改这里必须同步改那里。
 */

export type SpecGroupKey = "tutorial" | "paper" | "other";

export const SPEC_GROUPS: { key: SpecGroupKey; label: string; scenes: string[] }[] = [
  {
    key: "tutorial",
    label: "教程规范",
    scenes: ["default_tutorial", "knowledge_tutorial", "practical_tutorial", "reading_guide"],
  },
  { key: "paper", label: "练习与试卷规范", scenes: ["exercise", "exam_paper"] },
  { key: "other", label: "其他规范", scenes: [] },
];

export const SPEC_DELIVERABLE_STATUS: Record<string, string> = {
  required: "必须",
  on_request: "用户要求时",
  optional: "可选",
  forbidden: "禁止",
};

/** 阅读教程规范的 scene：后端对它走「按章注入 + 全书层后置」两阶段生成，与教程族语义不同。 */
export const READING_GUIDE_SCENE = "reading_guide";

export function specScene(spec: Pick<FormatSpec, "scene"> | null | undefined): string {
  return String(spec?.scene ?? "").trim();
}

export function specGroupKey(spec: Pick<FormatSpec, "scene"> | null | undefined): SpecGroupKey {
  const scene = specScene(spec);
  const hit = SPEC_GROUPS.find((group) => group.scenes.includes(scene));
  return hit ? hit.key : "other";
}

/** 规范族别标签：阅读教程规范单独点名，其余按组名。 */
export function specGroupLabel(spec: Pick<FormatSpec, "scene"> | null | undefined): string {
  if (specScene(spec) === READING_GUIDE_SCENE) return "阅读教程规范";
  return SPEC_GROUPS.find((group) => group.key === specGroupKey(spec))?.label ?? "其他规范";
}

/** 按分组整理规范列表；空组不出现，未知 scene 落到「其他规范」。 */
export function groupSpecs<T extends Pick<FormatSpec, "scene">>(
  specs: T[]
): { key: SpecGroupKey; label: string; specs: T[] }[] {
  return SPEC_GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    specs: (specs ?? []).filter((spec) => specGroupKey(spec) === group.key),
  })).filter((group) => group.specs.length > 0);
}

const text = (value: unknown) => String(value ?? "").trim();
const listText = (value: unknown) =>
  Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean).join("、") : "";

/**
 * 每段的注入阶段标注（来自 llm/prompts.py:_format_spec_block）。
 * 只在 stages 模式（偏好设置页的编辑预览）里追加，创建表单与插件不显示。
 */
const SECTION_STAGES: Record<string, string> = {
  输出目标与受众: "plan / outline / criteria / section",
  内容结构: "outline / section",
  参考示例: "outline / section",
  格式与表达: "section",
  必须遵守: "section",
  建议遵守: "section",
  可灵活调整: "section",
  禁止出现: "outline / section",
  验收标准: "criteria / section",
  自定义补充规则: "outline / section / 配套文件",
};

export type SpecPreviewOptions = {
  /** 追加「（plan / outline / section）」注入阶段标注；编辑者视角打开。 */
  stages?: boolean;
};

/**
 * 规范正文预览：段落顺序与 llm/prompts.py:_format_spec_block 的注入顺序一致，
 * 这样预览里看到的层级就是生成时模型看到的层级。空字段整段跳过，不留空标题。
 *
 * 偏好设置页的编辑预览、创建表单的「查看规范」共用本函数，三处显示保持一致
 * （Obsidian 插件里有一份等价实现，改这里要同步改插件）。
 */
export function specPreviewMarkdown(
  spec: Partial<FormatSpec> | null | undefined,
  options: SpecPreviewOptions = {}
): string {
  const data = spec ?? {};
  const stages = options.stages === true;
  const heading = (base: string) => {
    const stage = stages ? SECTION_STAGES[base] : "";
    if (base === "交付物") {
      return stages ? "## 交付物（结构由代码定死：一个交付物一章）" : "## 交付物（一个交付物一章）";
    }
    return stage ? `## ${base}（${stage}）` : `## ${base}`;
  };
  const deliverables = Array.isArray(data.deliverables) && data.deliverables.length
    ? data.deliverables
        .map(
          (item) =>
            `- ${text(item.name)}（${SPEC_DELIVERABLE_STATUS[item.status] ?? item.status ?? "可选"}）`
        )
        .join("\n")
    : stages
      ? "- 未配置结构化交付物"
      : "- 未配置结构化交付物（章节数与章名由大纲模型按知识逻辑决定）";

  const sections: [string, string[]][] = [
    [heading("匹配与适用"), [
      `适用任务：${text(data.applicable_tasks) || "未填写"}`,
      `适用意图：${listText(data.applicable_intents) || "未填写"}`,
      `排除场景：${listText(data.excluded_scenarios) || "无"}`,
      `排除意图：${listText(data.excluded_intents) || "无"}`,
      `触发关键词：${listText(data.trigger_keywords) || "未启用"}`,
      `排除关键词：${listText(data.excluded_keywords) || "无"}`,
    ]],
    [heading("输出目标与受众"), [
      text(data.output_goal) || text(data.description) || "未填写",
      text(data.target_reader) ? `目标受众：${text(data.target_reader)}` : "",
    ]],
    [heading("交付物"), [deliverables]],
    [heading("内容结构"), [text(data.content_structure)]],
    [heading("参考示例"), [text(data.reference_examples)]],
    [heading("格式与表达"), [text(data.format_rules)]],
    [heading("必须遵守"), [text(data.required_rules)]],
    [heading("建议遵守"), [text(data.suggested_rules)]],
    [heading("可灵活调整"), [text(data.flexible_rules)]],
    [heading("禁止出现"), [text(data.forbidden_rules)]],
    [heading("验收标准"), [text(data.acceptance_criteria)]],
    [heading("自定义补充规则"), [text(data.custom_markdown)]],
  ];

  // 头部：描述为空时不留空行。正文里刻意的空行（如 content_structure 的分段）必须原样保留，
  // 所以这里不做全局折叠。
  const description = text(data.description);
  const out: string[] = [`# ${text(data.name) || "未命名规范"}`];
  if (description) out.push("", description);
  out.push("");
  for (const [title, lines] of sections) {
    const body = lines.map((line) => text(line)).filter(Boolean);
    if (!body.length) continue;
    out.push(title, ...body, "");
  }
  return out.join("\n").trimEnd();
}
