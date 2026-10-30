# -*- coding: utf-8 -*-
"""真实模型链路实测（最小成本）：创建目标 -> 真实 diagnose -> 校验 token 记账/训练样本 -> 清理"""
import json, sys, time, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8000/api"   # 用户正在运行的真实后端（已配 deepseek）
def call(m, p, b=None, timeout=600):
    d = json.dumps(b, ensure_ascii=False).encode() if b is not None else None
    h = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:3001"} if d else {"Origin": "http://127.0.0.1:3001"}
    req = urllib.request.Request(B + p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            x = r.read(); return r.status, (json.loads(x.decode()) if x else None)
    except urllib.error.HTTPError as e:
        x = e.read()
        try: return e.code, json.loads(x.decode())
        except Exception: return e.code, x[:400].decode("utf-8", "replace")

st, g = call("POST", "/goals", {
    "title": "【实测临时】真实模型链路验证（勿动，测完自动删除）",
    "domain_key": "cs_it",
    "motivation": "验证真实模型生成链路是否可用",
    "application_context": "确认 diagnose 阶段能拿到真实模型输出与 provider token",
    "current_level": "有编程基础",
    "time_budget": "共 1 小时",
    "capability_level": "L1",
    "generation_tier": "fast",
})
assert st == 200, (st, g)
gid = g["id"]
print("created goal:", gid, "demo flag:", g.get("demo"))
t0 = time.time()
st, d = call("POST", f"/goals/{gid}/diagnose")
el = time.time() - t0
print(f"\ndiagnose status={st} elapsed={el:.1f}s")
if st == 200 and isinstance(d, dict):
    print("demo:", d.get("demo"))
    print("recommendation:", str(d.get("recommendation"))[:200])
    print("benefits len:", len(d.get("benefits") or ""))
    print("prerequisites len:", len(d.get("prerequisites") or ""))
    print("token_usage:", json.dumps(d.get("token_usage") or {}, ensure_ascii=False))
    print("=> 真实模型（demo=False）:", d.get("demo") is False)
    print("=> provider token 已记账:", (d.get("token_usage") or {}).get("usage_source") == "provider" and (d.get("token_usage") or {}).get("total_tokens", 0) > 0)
else:
    print("FAILED:", str(d)[:400])

st, u = call("GET", f"/goals/{gid}/usage")
print("\nusage endpoint:", st, json.dumps((u or {}).get("totals") or {}, ensure_ascii=False))
print("by_feature:", json.dumps(u.get("by_feature") or [], ensure_ascii=False)[:300] if isinstance(u, dict) else u)

st, s = call("GET", "/training/stats")
print("\ntraining totals:", json.dumps((s or {}).get("totals") or {}, ensure_ascii=False))

# 训练样本是否记录了真实 prompt/output
st, r = call("GET", f"/training/records?goal_id={gid}&limit=5")
if st == 200 and isinstance(r, dict):
    items = r.get("items") or []
    print(f"\ntraining records for this goal: {len(items)}")
    for it in items:
        print(f"  feature={it.get('feature')} model={it.get('model_name')} tokens={ (it.get('token_usage') or {}).get('total_tokens') } src={(it.get('token_usage') or {}).get('usage_source')} prompt_chars={it.get('prompt_chars')} output_chars={it.get('output_chars')}")
else:
    print("\ntraining records FAILED:", st, str(r)[:200])

print("\n--- cleanup ---")
st, p = call("DELETE", f"/goals/{gid}?purge=true")
print("purge:", st, json.dumps(p, ensure_ascii=False)[:300] if isinstance(p, dict) else p)
st, chk = call("GET", f"/goals/{gid}")
print("goal gone:", st == 404)
