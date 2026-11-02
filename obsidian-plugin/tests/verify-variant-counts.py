import io, re, sys, json

exported = io.open(sys.argv[1], encoding="utf-8").read()
ref = io.open(r"D:\BJH\基础代数一_课后习题汇编.md", encoding="utf-8").read().splitlines()

# 参考集统计：每章原题数
starts = [i for i, l in enumerate(ref) if l.startswith("## 第 1 章")]
body = ref[starts[-1]:]
chapter = None
in_section = False
orig = {}
for line in body:
    m = re.match(r"^## (第 \d+ 章)", line)
    if m:
        chapter = m.group(1); orig.setdefault(chapter, 0); in_section = False; continue
    if re.match(r"^### 习题", line) and chapter:
        in_section = True; continue
    if re.match(r"^\d+\.\s", line) and chapter and in_section:
        orig[chapter] += 1

# 导出文档统计：按章节切分
sections = re.split(r"(?m)^## ", exported)[1:]
report = []
ok = True
for sec in sections:
    head = sec.splitlines()[0].strip()
    m = re.match(r"^[一二三四五六七八九十]+、(第 \d+ 章)", head) or re.match(r"^(第 \d+ 章)", head)
    if not m:
        report.append((head, None, None, None, "非章节段")); continue
    ch = m.group(1)
    variants = re.findall(r"\*\*\d+\.\d+-\d+-V\d+\.\*\*", sec)
    comps = re.findall(r"\*\*\d+-C\d+\.\*\*", sec)
    expect_v = orig.get(ch, 0) * 2
    expect_c = 10
    good = len(variants) == expect_v and len(comps) == expect_c
    ok = ok and good
    report.append((ch, f"{len(variants)}/{expect_v}", f"{len(comps)}/{expect_c}", "", "OK" if good else "MISMATCH"))

for row in report:
    print(" | ".join(str(x) for x in row))
print("ANSWER_LEAK:", "答案：" in exported or "解析：" in exported)
print("VERIFY:", "PASS" if ok else "FAIL")
