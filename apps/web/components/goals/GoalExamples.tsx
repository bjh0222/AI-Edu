"use client";

/**
 * 用户输入范例：创建 / 定义学习目标时需要用户填写的字段，范例集中放在这一处，
 * 以「一条完整目标」的形式展示，供用户参照。新增输入字段时在这里补一行即可。
 */

export const GOAL_FIELD_EXAMPLES: { field: string; example: string }[] = [
  { field: "目标名称", example: "掌握命令行管道与重定向" },
  {
    field: "为什么要学",
    example: "日常要在终端处理日志和批量文件，重复手工操作太多，想把这些工作自动化",
  },
  {
    field: "学完要能做什么",
    example: "能用管道把 3 条命令串起来，从一份 500MB 的日志里筛出错误行并统计每类错误的次数",
  },
  {
    field: "当前基础",
    example: "会用 cd、ls、cat 等基本命令，但看到 | 和 > 组合的长命令就看不懂了",
  },
  { field: "可投入总时间", example: "共 10 小时，打算两周内用完" },
  { field: "补充笔记", example: "平时主要在 Windows Terminal 里练习，希望例子贴近日志分析场景" },
];

export function GoalExamples({ open = false }: { open?: boolean }) {
  return (
    <details
      open={open}
      className="mt-3 rounded-xl border border-line bg-[#faf9ff] px-3.5 py-2.5"
    >
      <summary className="cursor-pointer text-[11px] font-semibold text-brand select-none">
        填写范例（供参考，可直接照这个粒度写）
      </summary>
      <div className="mt-2 grid gap-1.5 text-[11px] leading-relaxed">
        {GOAL_FIELD_EXAMPLES.map((item) => (
          <div key={item.field} className="grid grid-cols-[max-content_1fr] gap-x-2.5 gap-y-1">
            <span className="font-semibold text-muted">{item.field}</span>
            <span className="text-[#4a4f5e]">{item.example}</span>
          </div>
        ))}
      </div>
    </details>
  );
}
