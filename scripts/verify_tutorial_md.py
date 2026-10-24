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


def strip_code(markdown: str) -> str:
    """去掉围栏代码块与行内代码，只保留会生效的 Markdown 文本。"""
    lines: list[str] = []
    fence: str | None = None
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
        # 行内代码：只保留非代码片段
        pieces = re.split(r"(`[^`\n]*`)", line)
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
