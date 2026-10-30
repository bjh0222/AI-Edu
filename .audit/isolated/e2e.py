# -*- coding: utf-8 -*-
"""端到端业务流程实测：目标 -> 诊断 -> 决定 -> 计划 -> 验收标准 -> 大纲 -> 章节 -> 导出 -> 知识网络 -> 训练数据 -> 备份/导入/删除"""
import json, sys, time, urllib.request, urllib.error, io

B = "http://127.0.0.1:8199/api"
PASS = FAIL = 0
RESULTS = []

def call(method, path, body=None, raw=False, timeout=300):
    data = None
    headers = {}
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(B + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            if raw:
                return r.status, payload, dict(r.headers)
            return r.status, (json.loads(payload.decode("utf-8")) if payload else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode("utf-8")), dict(e.headers)
        except Exception:
            return e.code, payload[:400].decode("utf-8", "replace"), {}

def step(name, expect, fn):
    global PASS, FAIL
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"EXCEPTION {type(e).__name__}: {e}"
    if ok:
        PASS += 1; RESULTS.append(("PASS", name, detail))
        print(f"PASS  {name:52} {detail}")
    else:
        FAIL += 1; RESULTS.append(("FAIL", name, detail))
        print(f"FAIL  {name:52} {detail}")
    return ok

sys.stdout.reconfigure(encoding="utf-8")

print("=" * 100)
print("阶段 A：创建目标（含硬性约束 / 挡位 / 能力层级 / 额外练习开关）")
print("=" * 100)
goal_body = {
    "title": "E2E 测试目标：用 grep/awk 排查线上错误日志",
    "domain_key": "cs_it",
    "motivation": "线上服务报错，需要自己快速定位而不是每次求助",
    "application_context": "在真实项目中独立完成日志排查",
    "current_level": "零基础，没用过命令行",
    "time_budget": "共 10 小时",
    "hard_constraints": "每章必须给出可复现的命令示例\n禁止出现「第 X 天」「每天」等日程表述",
    "capability_level": "L2",
    "generation_tier": "fast",
    "generate_extra_exercises": True,
}
st, goal, _ = call("POST", "/goals", goal_body)
gid = goal["id"] if isinstance(goal, dict) else None
step("POST /goals 创建目标", st == 200 and gid is not None, lambda: (
    st == 200 and gid is not None,
    f"status={st} id={gid} demo={goal.get('demo') if isinstance(goal,dict) else '?'}"))
if not gid:
    print("ABORT"); sys.exit(1)
step("目标字段正确落库（挡位/层级/约束/额外练习）", True, lambda: (
    goal.get("generation_tier") == "fast" and goal.get("capability_level") == "L2"
    and bool(goal.get("hard_constraints")) and goal.get("generate_extra_exercises") is True,
    f"tier={goal.get('generation_tier')} level={goal.get('capability_level')} "
    f"hard_constraints={len(goal.get('hard_constraints') or '')}字 extra_exercises={goal.get('generate_extra_exercises')}"))
step("非法能力层级归一化（传 L9 -> 回落 L2）", True, lambda: _check_level())

def _check_level():
    st2, g2, _ = call("POST", "/goals", {**goal_body, "title": "层级归一化测试", "capability_level": "L9"})
    ok = st2 == 200 and g2.get("capability_level") == "L2"
    if isinstance(g2, dict) and g2.get("id"):
        call("DELETE", f"/goals/{g2['id']}?purge=true")
    return ok, f"status={st2} capability_level={g2.get('capability_level') if isinstance(g2,dict) else g2}"

step("非法能力层级归一化（传 L9 -> 回落 L2）", True, _check_level)

print()
print("=" * 100)
print("阶段 B：价值诊断 -> 用户决定")
print("=" * 100)
st, d, _ = call("POST", f"/goals/{gid}/diagnose")
step("POST /goals/{id}/diagnose 生成诊断", st == 200 and isinstance(d, dict) and bool(d.get("recommendation")),
     lambda: (st == 200 and isinstance(d, dict) and bool(d.get("recommendation")),
              f"status={st} demo={d.get('demo') if isinstance(d,dict) else '?'} fields={[k for k in ('benefits','prerequisites','alternatives','recommendation') if isinstance(d,dict) and d.get(k)]}"))
st, d2, _ = call("GET", f"/goals/{gid}/diagnose")
step("GET /goals/{id}/diagnose 幂等读取", st == 200 and isinstance(d2, dict) and d2.get("id") == d.get("id"),
     lambda: (st == 200 and isinstance(d2, dict) and d2.get("id") == (d.get("id") if isinstance(d,dict) else None), f"status={st} same_id={isinstance(d2,dict) and d2.get('id')==(d.get('id') if isinstance(d,dict) else None)}"))
st, dec, _ = call("POST", f"/goals/{gid}/decision", {"decision": "proceed", "reason": "E2E 实测：继续推进"})
step("POST /goals/{id}/decision 记录用户决定", st == 200 and isinstance(dec, dict) and dec.get("user_decision") == "proceed",
     lambda: (st == 200 and isinstance(dec, dict) and dec.get("user_decision") == "proceed", f"status={st} user_decision={dec.get('user_decision') if isinstance(dec,dict) else dec}"))
st, bad, _ = call("POST", f"/goals/{gid}/decision", {"decision": "nonsense", "reason": "x"})
step("非法决定被拒绝（4xx）", 400 <= st < 500, lambda: (400 <= st < 500, f"status={st} detail={str(bad)[:120]}"))

print()
print("=" * 100)
print("阶段 C：学习计划 -> 验收标准 -> 一键同意")
print("=" * 100)
st, p, _ = call("POST", f"/goals/{gid}/plan")
step("POST /goals/{id}/plan 生成学习计划", st == 200 and isinstance(p, dict) and len(p.get("steps") or []) > 0,
     lambda: (st == 200 and isinstance(p, dict) and len(p.get("steps") or []) > 0,
              f"status={st} steps={len(p.get('steps') or []) if isinstance(p,dict) else '?'} plan_status={p.get('status') if isinstance(p,dict) else '?'}"))
st, c, _ = call("POST", f"/goals/{gid}/criteria")
step("POST /goals/{id}/criteria 生成验收标准", st == 200 and isinstance(c, list) and len(c) > 0,
     lambda: (st == 200 and isinstance(c, list) and len(c) > 0,
              f"status={st} count={len(c) if isinstance(c,list) else '?'} statuses={[x.get('status') for x in c][:4] if isinstance(c,list) else '?'}"))
st, ca, _ = call("POST", f"/goals/{gid}/criteria/confirm-all", {})
step("POST /criteria/confirm-all 一键同意", st == 200 and isinstance(ca, dict) and ca.get("confirmed", 0) > 0,
     lambda: (st == 200 and isinstance(ca, dict) and ca.get("confirmed", 0) > 0,
              f"status={st} confirmed={ca.get('confirmed') if isinstance(ca,dict) else '?'} changed={ca.get('changed') if isinstance(ca,dict) else '?'}"))
st, ca2, _ = call("POST", f"/goals/{gid}/criteria/confirm-all", {})
step("一键同意幂等（重复调用 changed=0）", st == 200 and isinstance(ca2, dict) and ca2.get("changed") == 0,
     lambda: (st == 200 and isinstance(ca2, dict) and ca2.get("changed") == 0, f"status={st} changed={ca2.get('changed') if isinstance(ca2,dict) else '?'}"))

cid = c[0]["id"] if isinstance(c, list) and c else None
if cid:
    st, rej, _ = call("PATCH", f"/criteria/{cid}", {"status": "rejected"})
    st3, ca3, _ = call("POST", f"/goals/{gid}/criteria/confirm-all", {})
    kept = [x for x in (ca3.get("criteria") or []) if x.get("id") == cid]
    step("一键同意不覆盖已拒绝项", kept and kept[0].get("status") == "rejected",
         lambda: (bool(kept) and kept[0].get("status") == "rejected", f"rejected 项状态={kept[0].get('status') if kept else 'MISSING'}"))
    call("PATCH", f"/criteria/{cid}", {"status": "confirmed"})

print()
print("GOAL_ID=" + gid)
print(f"\nSUMMARY pass={PASS} fail={FAIL}")
json.dump({"goal_id": gid, "results": RESULTS}, open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part1.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
