import io, re, sys
p = r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e2.py"
src = io.open(p, encoding="utf-8").read()
old_sig = "def step(name, fn):\n    global PASS, FAIL\n"
new_sig = "def step(name, fn=None, *legacy):\n    global PASS, FAIL\n"
assert old_sig in src, "sig not found"
src = src.replace(old_sig, new_sig, 1)
old_body = "    try: ok, detail = fn()\n"
new_body = ("    try:\n"
            "        fn2 = legacy[0] if (legacy and callable(legacy[0])) else fn\n"
            "        if callable(fn2):\n"
            "            ok, detail = fn2()\n"
            "        else:\n"
            "            ok, detail = bool(fn2 if fn2 is not None else fn), \"\"\n")
assert old_body in src, "body not found"
src = src.replace(old_body, new_body, 1)
io.open(p, "w", encoding="utf-8").write(src)
print("patched OK")
