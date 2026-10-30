import re, pathlib
targets = ["app/services/knowledge.py","app/services/format_specs.py","app/services/materials.py",
 "app/services/practice.py","app/services/usage.py","app/services/chat.py","app/services/utils.py",
 "app/learning/teaching_profile.py","app/learning/levels.py","app/llm/provider.py","app/llm/prompts.py",
 "app/llm/service.py","app/api/knowledge.py","app/api/practice.py","app/api/io.py","app/api/chat.py",
 "app/api/format_specs.py","app/schemas.py","app/services/tutorials.py","app/services/pipeline.py"]
for t in targets:
    p = pathlib.Path(t)
    if not p.exists(): print("MISSING", t); continue
    src = p.read_text(encoding="utf-8").splitlines()
    print(f"\n===== {t} ({len(src)} lines) =====")
    mod = None
    for i, line in enumerate(src):
        if i < 12 and line.startswith('"""'):
            mod = line.strip('" ')
        if re.match(r"^(def |class |    def |async def |    async def )", line):
            print(f"{i+1:5} {line.rstrip()[:150]}")
    if mod: print("  MODULE DOC:", mod[:160])
