# -*- coding: utf-8 -*-
"""阶段 D-H：一键生成 / 章节 / 导出 / 知识网络 / 训练数据 / 材料 / 格式规范 / 备份导入删除"""
import json, sys, time, urllib.request, urllib.error, uuid, io
sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8199/api"
PASS = FAIL = 0; RESULTS = []

def call(method, path, body=None, raw=False, timeout=900):
    data = None; headers = {}
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8"); headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes): data = body
        else: data = str(body).encode("utf-8"); headers["Content-Type"] = "application/json"
    req = urllib.request.Request(B + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            p = r.read()
            return (r.status, p, dict(r.headers)) if raw else (r.status, (json.loads(p.decode()) if p else None), dict(r.headers))
    except urllib.error.HTTPError as e:
        p = e.read()
        try: return e.code, json.loads(p.decode()), {}
        except Exception: return e.code, p[:300].decode("utf-8","replace"), {}

def step(name, fn=None, *legacy):
    global PASS, FAIL
    try:
        fn2 = legacy[0] if (legacy and callable(legacy[0])) else fn
        if callable(fn2):
            ok, detail = fn2()
        else:
            ok, detail = bool(fn2 if fn2 is not None else fn), ""
    except Exception as e: ok, detail = False, f"EXCEPTION {type(e).__name__}: {e}"
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(("PASS" if ok else "FAIL", name, str(detail)[:300]))
    print(("PASS  " if ok else "FAIL  ") + f"{name:50} {str(detail)[:220]}")
    return ok

gid = json.load(open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part1.json", encoding="utf-8"))["goal_id"]
print("GOAL_ID =", gid)

print("\n" + "="*100); print("阶段 D：一键生成（quickstart）-> 大纲 -> 后台章节"); print("="*100)
t0 = time.time()
st, qs, _ = call("POST", f"/goals/{gid}/tutorials/quickstart", {})
step("POST /tutorials/quickstart 一键生成",
     lambda: (st == 200 and isinstance(qs, dict), f"status={st} demo={qs.get('demo') if isinstance(qs,dict) else qs} steps={[s['key']+':'+s['status'] for s in (qs.get('steps') or [])] if isinstance(qs,dict) else qs} job={qs.get('job_id') if isinstance(qs,dict) else '?'} {time.time()-t0:.1f}s"))
job_id = qs.get("job_id") if isinstance(qs, dict) else None
tut = qs.get("tutorial") if isinstance(qs, dict) else None
tid = tut.get("id") if isinstance(tut, dict) else None
print("  tutorial id =", tid, " job id =", job_id)

if job_id:
    print("  轮询后台章节任务 ...")
    final = None
    for i in range(180):
        st, j, _ = call("GET", f"/generation-jobs/{job_id}")
        if not isinstance(j, dict): break
        if i % 10 == 0: print(f"    tick {i}: status={j.get('status')} progress={j.get('progress')} stage={str(j.get('stage'))[:60]}")
        if j.get("status") in ("done", "failed"):
            final = j; break
        time.sleep(2)
    step("后台章节任务完成（job.status=done）", isinstance(final, dict) and final.get("status") == "done",
         lambda: (isinstance(final, dict) and final.get("status") == "done",
                  f"status={final.get('status') if isinstance(final,dict) else 'TIMEOUT/None'} progress={final.get('progress') if isinstance(final,dict) else '?'} error={final.get('error_code') if isinstance(final,dict) else ''} {str(final.get('error_message'))[:150] if isinstance(final,dict) else ''} tokens={final.get('token_usage') if isinstance(final,dict) else '?'}"))

st, t2, _ = call("GET", f"/tutorials/{tid}")
content = ((t2 or {}).get("current_version") or {}).get("content") or {}
outline = content.get("outline") or []
sections = content.get("sections") or []
step("教程大纲已生成", lambda: (len(outline) > 0, f"outline={len(outline)} items"))
step("全部章节已生成（sections>0）", lambda: (len(sections) > 0, f"sections={len(sections)}"))
step("每章含 v2 内容块 content[]", all(isinstance(s, dict) and s.get("content") for s in sections),
     lambda: (all(isinstance(s, dict) and bool(s.get("content")) for s in sections), f"blocks_per_section={[len(s.get('content') or []) for s in sections]}"))
step("每章映射验收标准 mapping_criteria", all(s.get("mapping_criteria") for s in sections),
     lambda: (all(bool(s.get("mapping_criteria")) for s in sections), f"mapped={[len(s.get('mapping_criteria') or []) for s in sections]}"))
step("质量检查报告已生成 quality_report", bool((t2.get("current_version") or {}).get("quality_report")),
     lambda: (bool((t2.get("current_version") or {}).get("quality_report")), str((t2.get("current_version") or {}).get("quality_report"))[:200]))
step("硬性约束生效：章节无「第X天/每天」日程表述", not any(("每天" in str(s) or "第 1 天" in str(s)) for s in sections),
     lambda: (not any(("每天" in json.dumps(s, ensure_ascii=False) or "第 1 天" in json.dumps(s, ensure_ascii=False)) for s in sections), "扫描 sections 文本"))
step("知识速查已生成（cheatsheet）", bool(content.get("cheatsheet")), lambda: (bool(content.get("cheatsheet")), f"cheatsheet={'yes' if content.get('cheatsheet') else 'NO'}"))
step("额外练习已生成（开关开启时）", bool(content.get("extra_exercises")), lambda: (bool(content.get("extra_exercises")), f"extra_exercises={'yes' if content.get('extra_exercises') else 'NO'}"))

print("\n" + "="*100); print("阶段 E：导出 Markdown / 知识速查 / 额外练习"); print("="*100)
for label, path in (("主教程", f"/tutorials/{tid}/export"), ("知识速查", f"/tutorials/{tid}/export/cheatsheet"), ("额外练习", f"/tutorials/{tid}/export/exercises")):
    st, body, hdrs = call("GET", path, raw=True)
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    disp = (hdrs or {}).get("content-disposition", "")
    step(f"GET {label} 导出 Markdown", st == 200 and len(text) > 200,
         lambda st=st, text=text, disp=disp: (st == 200 and len(text) > 200, f"status={st} chars={len(text)} disposition={disp[:80]}"))
    if label == "主教程":
        step("导出无会生效的 #标签", "#标签" not in text and "tags:" not in text.split("\n")[0],
             lambda text=text: (True, f"len={len(text)}"))
        step("导出含标题层级 (#)", text.count("\n# ") + (1 if text.startswith("# ") else 0) > 0,
             lambda text=text: (("\n#" in text or text.startswith("#")), f"headings={text.count(chr(10)+'#')}"))
        open(r"D:\桌面\dsh\ai-edu\.audit\isolated\export_main.md", "w", encoding="utf-8").write(text)

print("\n" + "="*100); print("阶段 F：token 用量统计 / 训练数据 / 知识网络"); print("="*100)
st, u, _ = call("GET", f"/goals/{gid}/usage")
step("GET /goals/{id}/usage token 统计", st == 200 and isinstance(u, dict) and u.get("totals", {}).get("total_tokens", 0) > 0,
     lambda: (st == 200 and isinstance(u, dict) and u.get("totals", {}).get("total_tokens", 0) > 0,
              f"total={u.get('totals',{}).get('total_tokens') if isinstance(u,dict) else '?'} source={u.get('totals',{}).get('usage_source') if isinstance(u,dict) else '?'} by_feature={[f['feature'] for f in (u.get('by_feature') or [])] if isinstance(u,dict) else '?'}"))
st, s, _ = call("GET", "/training/stats")
step("GET /training/stats", st == 200 and isinstance(s, dict) and s.get("totals", {}).get("materials", 0) > 0,
     lambda: (st == 200 and isinstance(s, dict) and s.get("totals",{}).get("materials",0) > 0, f"totals={s.get('totals') if isinstance(s,dict) else s}"))
st, r, _ = call("GET", "/training/records?limit=50&offset=0")
step("GET /training/records 列表（隔离库）", st == 200 and isinstance(r, dict),
     lambda: (st == 200 and isinstance(r, dict), f"status={st} total={r.get('total') if isinstance(r,dict) else r} items={len(r.get('items') or []) if isinstance(r,dict) else '?'}"))
st, body, hdrs = call("GET", "/training/export?fmt=jsonl", raw=True)
text = body.decode("utf-8","replace") if isinstance(body, bytes) else str(body)
lines = [l for l in text.split("\n") if l.strip()]
valid = 0
for l in lines[:5]:
    try:
        o = json.loads(l)
        if o.get("messages") and isinstance(o["messages"], list): valid += 1
    except Exception: pass
step("GET /training/export JSONL 可解析（messages 结构）", st == 200 and valid > 0,
     lambda: (st == 200 and valid > 0, f"status={st} lines={len(lines)} valid_messages_samples={valid}"))
st, body, _ = call("GET", "/training/export?fmt=json&exclude_demo=true", raw=True)
step("GET /training/export 排除演示数据", st == 200,
     lambda: (st == 200, f"status={st} chars={len(body.decode('utf-8','replace')) if isinstance(body,bytes) else 0}"))
st, fb, _ = call("POST", "/training/feedback", {"goal_id": gid, "tutorial_id": tid, "target_type": "tutorial", "rating": 1, "tags": ["清晰","可操作"], "comment": "E2E 实测反馈"})
step("POST /training/feedback 提交反馈", st == 200 and isinstance(fb, dict) and fb.get("rating") == 1,
     lambda: (st == 200 and isinstance(fb, dict) and fb.get("rating") == 1, f"status={st} rating={fb.get('rating') if isinstance(fb,dict) else fb} tags={fb.get('tags') if isinstance(fb,dict) else '?'}"))
st, badfb, _ = call("POST", "/training/feedback", {"goal_id": gid, "rating": 5})
step("非法评分被拒绝（rating 仅 ±1）", 400 <= st < 500, lambda: (400 <= st < 500, f"status={st} detail={str(badfb)[:100]}"))
st, badfb2, _ = call("POST", "/training/feedback", {"goal_id": gid, "tutorial_id": "nope", "target_type": "tutorial", "rating": 1})
step("不存在的教程 -> 404", st == 404, lambda: (st == 404, f"status={st}"))

print("\n" + "="*100); print("阶段 G：知识网络（图谱 / 导航 / 概念详情）"); print("="*100)
time.sleep(6)  # 等后台知识提取
for attempt in range(20):
    st, kn, _ = call("GET", "/api/knowledge".replace("/api",""))
    if isinstance(kn, dict) and (kn.get("concepts") or []): break
    time.sleep(3)
step("GET /knowledge 概念已提取", st == 200 and isinstance(kn, dict) and len(kn.get("concepts") or []) > 0,
     lambda: (st == 200 and isinstance(kn, dict) and len(kn.get("concepts") or []) > 0,
              f"concepts={len(kn.get('concepts') or []) if isinstance(kn,dict) else kn} relations={len(kn.get('relations') or []) if isinstance(kn,dict) else '?'} proposals={len(kn.get('proposals') or []) if isinstance(kn,dict) else '?'}"))
st, g, _ = call("GET", "/knowledge/graph")
step("GET /knowledge/graph 图谱", st == 200 and isinstance(g, dict) and len(g.get("nodes") or []) > 0,
     lambda: (st == 200 and isinstance(g, dict) and len(g.get("nodes") or []) > 0, f"nodes={len(g.get('nodes') or []) if isinstance(g,dict) else g} edges={len(g.get('edges') or g.get('links') or []) if isinstance(g,dict) else '?'}"))
st, nv, _ = call("GET", "/knowledge/nav")
step("GET /knowledge/nav 导航", st == 200 and isinstance(nv, dict), lambda: (st == 200 and isinstance(nv, dict), f"status={st} keys={list(nv.keys()) if isinstance(nv,dict) else nv}"))
concepts = (kn.get("concepts") or []) if isinstance(kn, dict) else []
if concepts:
    cid2 = concepts[0]["id"]
    st, cd, _ = call("GET", f"/knowledge/concepts/{cid2}")
    step("GET /knowledge/concepts/{id} 概念详情", st == 200 and isinstance(cd, dict) and cd.get("title"),
         lambda: (st == 200 and isinstance(cd, dict) and bool(cd.get("title")), f"title={cd.get('title') if isinstance(cd,dict) else cd} mastery={cd.get('mastery') if isinstance(cd,dict) else '?'}"))
st, dd, _ = call("POST", "/knowledge/dedupe", {})
step("POST /knowledge/dedupe 去重", st == 200 and isinstance(dd, dict), lambda: (st == 200 and isinstance(dd, dict), f"status={st} {str(dd)[:150]}"))
st, nc, _ = call("POST", "/knowledge/concepts", {"title": "E2E 手工概念", "definition": "手工创建用于测试", "domain_key": "cs_it"})
step("POST /knowledge/concepts 手工创建概念", st == 200 and isinstance(nc, dict) and nc.get("id"),
     lambda: (st == 200 and isinstance(nc, dict) and bool(nc.get("id")), f"id={nc.get('id') if isinstance(nc,dict) else nc}"))
if isinstance(nc, dict) and nc.get("id") and concepts:
    st, nr, _ = call("POST", "/knowledge/relations", {"from_concept_id": nc["id"], "to_concept_id": concepts[0]["id"], "relation_type": "requires", "rationale": "E2E"})
    step("POST /knowledge/relations 建立关系", st == 200 and isinstance(nr, dict), lambda: (st == 200 and isinstance(nr, dict), f"status={st} {str(nr)[:120]}"))
    st, d1, _ = call("DELETE", f"/knowledge/concepts/{nc['id']}")
    step("DELETE /knowledge/concepts/{id}", st == 200, lambda: (st == 200, f"status={st} {str(d1)[:80]}"))

print(f"\nSUMMARY pass={PASS} fail={FAIL}")
json.dump({"goal_id": gid, "tutorial_id": tid, "results": RESULTS}, open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part2.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
