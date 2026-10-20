"use client";

import Link from "next/link";
import type { Criterion, OutlineItem, Section, TokenUsage } from "@/lib/types";
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

/** 单节正文：说明、步骤、练习、变式、常见错误、来源与验收映射。 */
export function SectionContent({
  section,
  criteria,
}: {
  section: Section;
  criteria?: Criterion[];
}) {
  const critById = new Map((criteria ?? []).map((c) => [c.id, c.statement]));
  return (
    <div className="grid gap-2">
      {section.goal_statement && <div className="text-[11px] text-muted">{section.goal_statement}</div>}

      {section.explanation.length > 0 && (
        <div className="grid gap-1.5">
          {section.explanation.map((block, index) => (
            <div key={index} className="rounded-lg bg-[#fafbfc] p-2.5 text-[11px] leading-relaxed">
              <b className="text-[#4f45a6]">{block.heading}</b>
              <div className="whitespace-pre-wrap">{block.body}</div>
            </div>
          ))}
        </div>
      )}

      {section.exercises.length > 0 && (
        <div className="text-[11px]">
          <div className="mb-1 text-[10px] font-bold text-muted">练习</div>
          <ul className="list-disc pl-4 leading-relaxed text-[#33415c]">
            {section.exercises.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {section.steps.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-bold text-muted">操作步骤</div>
          <ol className="grid gap-1.5">
            {section.steps.map((step, index) => (
              <li key={index} className="rounded-lg border border-line p-2.5 text-[11px] leading-relaxed">
                <div className="font-semibold">{step.text}</div>
                <div className="mt-0.5 text-muted">预期结果：{step.expected_result}</div>
                <div className="text-muted">验证方式：{step.verification}</div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {section.examples.length > 0 && (
        <div className="text-[11px]">
          <div className="mb-1 text-[10px] font-bold text-muted">示例</div>
          <ul className="list-disc pl-4 leading-relaxed text-[#33415c]">
            {section.examples.map((item, index) => (
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

      {section.common_errors.length > 0 && (
        <div className="text-[11px]">
          <div className="mb-1 text-[10px] font-bold text-muted">常见错误</div>
          <ul className="grid gap-1">
            {section.common_errors.map((item, index) => (
              <li key={index} className="text-muted">
                <b className="text-[#a33]">{item.error}</b> · {item.cause} · 排查：{item.diagnose}
              </li>
            ))}
          </ul>
        </div>
      )}

      {section.mapping_criteria.length > 0 && (
        <div className="text-[10px] text-muted">
          对应验收标准：
          {section.mapping_criteria.map((cid) => (
            <div key={cid}>· {critById.get(cid) ?? cid}</div>
          ))}
        </div>
      )}

      {section.sources.length > 0 && (
        <div className="text-[10px] text-muted">
          来源：
          {section.sources.map((source, index) => (
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
