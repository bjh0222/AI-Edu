"""校验 Obsidian 教程 Markdown 的交付质量。

检查项：
1. 没有会生效的 Obsidian 标签（`#标签`，frontmatter `tags:` 也算）；
2. 双链 `[[...]]` 全部能在 Vault 中解析到真实笔记（排除代码块/行内代码里的语法示例）；
3. 统计标题、章节数与有效链接，便于人工复核。

用法：
    python scripts/verify_tutorial_md.py "D:/vault/AI Edu/xxx-教程.md" --vault "D:/vault"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"!?\[\[([^\[\]\n]+)\]\]")
TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)")


# 行内代码与四种数学记法：都不含会生效的双链 / 标签，校验前一律剔除
_INLINE_SKIP_RE = re.compile(
    r"(`[^`\n]*`"              # 行内代码
    r"|\$\$[^$\n]*\$\$"        # 行内 $$…$$
    r"|\\\[[^\n]*?\\\]"      # 行内 \[…\]
    r"|\\\([^\n]*?\\\)"      # 行内 \(…\)
    r"|\$[^$\n]+\$)"            # 行内 $…$
)


def strip_code(markdown: str) -> str:
    r"""去掉围栏代码块、行内代码与数学公式，只保留会生效的 Markdown 文本。

    数学记法必须一并剔除：形式幂级数环 \(R[[x]]\)、矩阵 \([[a,b],[c,d]]\) 里的
    [[…]] 是记号而不是双链，否则校验会报出一批并不存在的断链。
    """
    lines: list[str] = []
    fence: str | None = None
    in_math = False
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        # $$ 与 \[ 围栏：整块都是公式。按「开/闭」净差翻转状态——
        # 同一行自闭合时不翻转；单独一行只有闭合符时也必须翻回来，
        # 否则后续正文会被整段吞掉（校验将漏掉真实断链）。
        if stripped.count("$$") % 2 == 1:
            in_math = not in_math
            continue
        opens, closes = stripped.count("\\["), stripped.count("\\]")
        if opens > closes:
            in_math = True
            continue
        if closes > opens:
            in_math = False
        if in_math:
            continue
        # 行内代码与行内公式：只保留非代码、非公式片段
        pieces = _INLINE_SKIP_RE.split(line)
        lines.append("".join(piece for idx, piece in enumerate(pieces) if idx % 2 == 0))
    return "\n".join(lines)


def frontmatter(markdown: str) -> str:
    if not markdown.startswith("---"):
        return ""
    parts = markdown.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def active_links(markdown: str) -> list[str]:
    targets: list[str] = []
    for raw in LINK_RE.findall(strip_code(markdown)):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target.removesuffix(".md").split("/")[-1])
    return targets


def active_tags(markdown: str) -> list[str]:
    return TAG_RE.findall(strip_code(markdown))


def verify(path: Path, vault: Path) -> dict:
    markdown = path.read_text(encoding="utf-8")
    names = {p.stem for p in vault.rglob("*.md")} if vault.exists() else set()
    links = active_links(markdown)
    unresolved = [link for link in links if vault.exists() and link not in names]
    report = {
        "file": str(path),
        "chars": len(markdown),
        "lines": len(markdown.splitlines()),
        "h2_headings": len(re.findall(r"(?m)^##\s+\S", strip_code(markdown))),
        "frontmatter_tags": bool(re.search(r"(?m)^tags:", frontmatter(markdown))),
        "active_tags": active_tags(markdown),
        "active_links": links,
        "unresolved_links": unresolved,
        "ok": not active_tags(markdown)
        and not re.search(r"(?m)^tags:", frontmatter(markdown))
        and not unresolved,
    }
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--vault", default="")
    args = parser.parse_args(argv)
    vault = Path(args.vault) if args.vault else Path("")
    reports = [verify(Path(item), vault) for item in args.files]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["ok"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
