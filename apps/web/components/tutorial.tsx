"use client";

import Link from "next/link";
import type { ContentBlock, Criterion, OutlineItem, Section, TeachingPlan, TokenUsage } from "@/lib/types";
import { CONTENT_TYPE_LABELS } from "@/lib/types";
import { fmtTokens, usageSourceLabel } from "@/lib/format";

/** 大纲列表：每一步都可点进详情（有章节 → 章节详情；仅大纲 → 教程详情锚点）。 */
export function OutlineList({
  tutorialId,
  outline,
  sections,
}: {
  tutorialId: string;
  outline: OutlineItem[];
  sections: Section[];
}) {
  return (
    <ol className="grid gap-1.5">
      {outline.map((item, index) => {
        const section = sections[index];
        const href = section
          ? `/tutorials/${tutorialId}/sections/${section.id}`
          : `/tutorials/${tutorialId}#outline-${index}`;
        return (
          <li key={item.id || index} id={`outline-${index}`}>
            <Link
              href={href}
              className="flex items-center gap-2 rounded-lg bg-[#fafbfc] px-3 py-2 text-[11px] transition-colors hover:bg-[#f4f2ff]"
            >
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-white text-[10px] font-bold text-brand">
                {index + 1}
              </span>
              <span className="font-semibold">{item.title}</span>
              {item.content_type ? (
                <span className="shrink-0 rounded bg-[#efeaff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6255e8]">
                  {CONTENT_TYPE_LABELS[item.content_type] ?? item.content_type}
                </span>
              ) : null}
              <span className="ml-auto shrink-0 text-[10px] text-muted">
                {item.criteria_ids.length} 条标准
                {section?.token_usage
                  ? ` · ${fmtTokens(section.token_usage.total_tokens)} tokens`
                  : " · 待生成"}
              </span>
              <span className="shrink-0 text-[10px] font-semibold text-brand">查看 →</span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

/** 内容块默认标题（与后端渲染保持一致）。 */
const BLOCK_HEADINGS: Record<string, string> = {
  text: "讲解",
  key_point: "关键结论",
  formula: "公式与推导",
  steps: "操作步骤",
  table: "表格",
  example: "示例",
  comparison: "对比分析",
  method_summary: "方法归纳",
  diagram: "概念关系图",
  memory: "记忆材料",
  note: "注意事项",
};

/** 内容块：v2 结构按块渲染。 */
function BlockView({ block }: { block: ContentBlock }) {
  const heading = block.title?.trim() || BLOCK_HEADINGS[block.type] || "讲解";
  const isQuote = block.type === "key_point" || block.type === "note";
  return (
    <div className="rounded-lg bg-[#fafbfc] p-2.5 text-[11px] leading-relaxed">
      <b className="text-[#4f45a6]">{heading}</b>
      <div className={`whitespace-pre-wrap ${isQuote ? "border-l-2 border-[#c9c2ff] pl-2" : ""}`}>
        {block.body}
      </div>
    </div>
  );
}

/** 单节正文：v2 内容块结构优先；旧结构（explanation/steps/…）原样兼容渲染。 */
export function SectionContent({
  section,
  criteria,
}: {
  section: Section;
  criteria?: Criterion[];
}) {
  const critById = new Map((criteria ?? []).map((c) => [c.id, c.statement]));
  const isV2 = (section.content?.length ?? 0) > 0;
  return (
    <div className="grid gap-2">
      {isV2 ? (
        <>
          {section.purpose && <div className="text-[11px] text-muted">{section.purpose}</div>}
          {section.content_type && (
            <div>
              <span className="rounded bg-[#efeaff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6255e8]">
                {CONTENT_TYPE_LABELS[section.content_type] ?? section.content_type}
              </span>
            </div>
          )}
          {(section.content ?? []).map((block, index) => (
            <BlockView key={index} block={block} />
          ))}
          {(section.key_takeaways?.length ?? 0) > 0 && (
            <div className="text-[11px]">
              <div className="mb-1 text-[10px] font-bold text-muted">核心结论</div>
              <ul className="list-disc pl-4 leading-relaxed text-[#33415c]">
                {section.key_takeaways!.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {(section.prerequisite_refs?.length ?? 0) > 0 && (
            <div className="text-[10px] text-muted">
              前置知识：{section.prerequisite_refs!.join("、")}
            </div>
          )}
        </>
      ) : (
        <>
          {section.goal_statement && <div className="text-[11px] text-muted">{section.goal_statement}</div>}
          {(section.explanation?.length ?? 0) > 0 && (
            <div className="grid gap-1.5">
              {section.explanation!.map((block, index) => (
                <div key={index} className="rounded-lg bg-[#fafbfc] p-2.5 text-[11px] leading-relaxed">
                  <b className="text-[#4f45a6]">{block.heading}</b>
                  <div className="whitespace-pre-wrap">{block.body}</div>
                </div>
              ))}
            </div>
          )}
          {(section.steps?.length ?? 0) > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-bold text-muted">操作步骤</div>
              <ol className="grid gap-1.5">
                {section.steps!.map((step, index) => (
                  <li key={index} className="rounded-lg border border-line p-2.5 text-[11px] leading-relaxed">
                    <div className="font-semibold">{step.text}</div>
                    <div className="mt-0.5 text-muted">预期结果：{step.expected_result}</div>
                    <div className="text-muted">验证方式：{step.verification}</div>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {(section.examples?.length ?? 0) > 0 && (
            <div className="text-[11px]">
              <div className="mb-1 text-[10px] font-bold text-muted">示例</div>
              <ul className="list-disc pl-4 leading-relaxed text-[#33415c]">
                {section.examples!.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {section.variation_task && (
            <div className="rounded-lg border border-[#e7e3ff] bg-[#f7f6ff] p-2.5 text-[11px] leading-relaxed">
              <b className="text-[#6255e8]">变式任务：</b>
              {section.variation_task}
            </div>
          )}
        </>
      )}

      {(section.exercises?.length ?? 0) > 0 && (
        <div className="text-[11px]">
          <div className="mb-1 text-[10px] font-bold text-muted">练习</div>
          <ul className="list-disc pl-4 leading-relaxed text-[#33415c]">
            {section.exercises!.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {(section.common_errors?.length ?? 0) > 0 && (
        <div className="text-[11px]">
          <div className="mb-1 text-[10px] font-bold text-muted">常见错误</div>
          <ul className="grid gap-1">
            {section.common_errors!.map((item, index) => (
              <li key={index} className="text-muted">
                <b className="text-[#a33]">{item.error}</b> · {item.cause} · 排查：{item.diagnose}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(section.mapping_criteria?.length ?? 0) > 0 && (
        <div className="text-[10px] text-muted">
          对应验收标准：
          {section.mapping_criteria.map((cid) => (
            <div key={cid}>· {critById.get(cid) ?? cid}</div>
          ))}
        </div>
      )}

      {(section.sources?.length ?? 0) > 0 && (
        <div className="text-[10px] text-muted">
          来源：
          {section.sources!.map((source, index) => (
            <span key={index} className="mr-2">
              {source.title}
              {source.note ? `（${source.note}）` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** token 消耗行：本版本 / 教程累计 / 目标累计。 */
export function TokenLine({
  versionTokens,
  tutorialTokens,
  goalTokens,
}: {
  versionTokens?: TokenUsage;
  tutorialTokens?: TokenUsage;
  goalTokens?: TokenUsage;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-[#f7f6ff] px-3 py-2 text-[10px] text-[#5a6a86]">
      <span>
        本次生成：
        <b className="text-brand">{fmtTokens(versionTokens?.total_tokens)}</b> tokens
      </span>
      <span>
        教程累计：
        <b className="text-brand">{fmtTokens(tutorialTokens?.total_tokens)}</b>
      </span>
      <span>
        目标累计：
        <b className="text-brand">{fmtTokens(goalTokens?.total_tokens)}</b>
      </span>
      <span className="text-[#99a2b3]">
        {usageSourceLabel(
          tutorialTokens?.usage_source || goalTokens?.usage_source || versionTokens?.usage_source
        )}
      </span>
    </div>
  );
}

const RULE_TYPE_LABELS: Record<string, string> = {
  forbidden: "禁止",
  required: "必须",
  default: "默认偏好",
  conditional: "条件规则",
};

/** 本次教程实际采用的教学规则；用 details 收起，不挤占正文阅读空间。 */
export function TeachingPlanNotice({ plan }: { plan?: TeachingPlan }) {
  const rules = plan?.rules ?? [];
  const decisions = plan?.decisions ?? [];
  const overrides = plan?.task_overrides ?? [];
  const conflicts = plan?.unresolved_conflicts ?? [];
  if (!rules.length && !decisions.length && !overrides.length && !conflicts.length) return null;

  return (
    <details className="mb-3 rounded-lg border border-line bg-[#fbfcff] px-3 py-2">
      <summary className="cursor-pointer text-[11px] font-semibold text-[#39455d]">
        本次个性化教学要求
      </summary>
      <div className="mt-2 grid gap-2 text-[10px] leading-relaxed text-[#5a6a86]">
        {rules.length > 0 && (
          <ul className="grid gap-1">
            {rules.map((rule) => (
              <li key={rule.id}>
                <b className="text-[#6255e8]">{RULE_TYPE_LABELS[rule.rule_type] ?? rule.rule_type}</b>
                {rule.hard ? "（硬约束）" : ""}：{rule.text}
              </li>
            ))}
          </ul>
        )}
        {decisions.length > 0 && (
          <div>
            <b>本次教学决策</b>
            <ul className="mt-1 grid gap-0.5">
              {decisions.map((item, index) => <li key={index}>· {item}</li>)}
            </ul>
          </div>
        )}
        {overrides.length > 0 && (
          <div>
            <b>本次任务覆盖的默认偏好</b>
            <ul className="mt-1 grid gap-0.5">
              {overrides.map((item, index) => <li key={index}>· {item}</li>)}
            </ul>
          </div>
        )}
        {conflicts.length > 0 && (
          <div className="text-[#a33]">
            <b>未消解的硬约束冲突</b>
            <ul className="mt-1 grid gap-0.5">
              {conflicts.map((item, index) => <li key={index}>· {item}</li>)}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
