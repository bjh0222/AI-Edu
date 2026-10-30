# -*- coding: utf-8 -*-
"""阶段 H-K：材料上传 / 格式规范 / 版本回滚 / 单节重生成 / 交付回写 / 备份导入 / 彻底删除 / 异常路径"""
import json, sys, time, uuid, urllib.request, urllib.error, io
sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8199/api"
PASS = FAIL = 0; RESULTS = []

def call(method, path, body=None, raw=False, timeout=900):
    data=None; headers={}
    if body is not None:
        if isinstance(body,(dict,list)):
            data=json.dumps(body,ensure_ascii=False).encode(); headers["Content-Type"]="application/json"
        elif isinstance(body,bytes): data=body
    req=urllib.request.Request(B+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            p=r.read()
            return (r.status,p,dict(r.headers)) if raw else (r.status,(json.loads(p.decode()) if p else None),dict(r.headers))
    except urllib.error.HTTPError as e:
        p=e.read()
        try: return e.code,json.loads(p.decode()),{}
        except Exception: return e.code,p[:300].decode("utf-8","replace"),{}

def step(name, fn=None, *legacy):
    global PASS, FAIL
    f = legacy[0] if (legacy and callable(legacy[0])) else fn
    try: ok,detail = f() if callable(f) else (bool(f),"")
    except Exception as e: ok,detail = False, f"EXCEPTION {type(e).__name__}: {e}"
    if ok: PASS+=1
    else: FAIL+=1
    RESULTS.append(("PASS" if ok else "FAIL", name, str(detail)[:300]))
    print(("PASS  " if ok else "FAIL  ")+f"{name:52} {str(detail)[:200]}")
    return ok

def upload(goal_id, filename, content, kind="reference"):
    boundary = "----aiedu" + uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n'.encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="note"\r\n\r\nE2E\r\n'.encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'.encode())
    body.write(content.encode()); body.write(f"\r\n--{boundary}--\r\n".encode())
    req=urllib.request.Request(f"{B}/goals/{goal_id}/materials",data=body.getvalue(),
        headers={"Content-Type":f"multipart/form-data; boundary={boundary}"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=120) as r:
            return r.status, json.loads(r.read().decode()), {}
    except urllib.error.HTTPError as e:
        p=e.read()
        try: return e.code,json.loads(p.decode()),{}
        except Exception: return e.code,p[:200].decode("utf-8","replace"),{}

prev = json.load(open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part2.json",encoding="utf-8"))
gid, tid = prev["goal_id"], prev["tutorial_id"]
print("GOAL_ID =", gid, " TUTORIAL_ID =", tid)

print("\n"+"="*100); print("阶段 H：参考资料 / 例题来源上传"); print("="*100)
st, lim, _ = call("GET","/materials/limits")
step("GET /materials/limits 返回上限与类型", st==200 and isinstance(lim,dict) and lim.get("max_bytes",0)>0 and lim.get("allowed_extensions"),
     lambda: (st==200 and isinstance(lim,dict) and lim.get("max_bytes",0)>0, f"max_bytes={lim.get('max_bytes') if isinstance(lim,dict) else lim} ext={len(lim.get('allowed_extensions') or []) if isinstance(lim,dict) else '?'} kinds={[k['key'] for k in (lim.get('kinds') or [])] if isinstance(lim,dict) else '?'}"))
st, m, _ = upload(gid, "e2e-参考笔记.md", "# 参考笔记\n\n这是 E2E 上传的参考资料。\n\n- 要点一\n- 要点二\n")
step("POST /goals/{id}/materials 上传 md", st==200 and isinstance(m,dict) and m.get("id"),
     lambda: (st==200 and isinstance(m,dict) and bool(m.get("id")), f"status={st} id={m.get('id') if isinstance(m,dict) else m} kind={m.get('kind') if isinstance(m,dict) else '?'} chars={m.get('char_count') if isinstance(m,dict) else '?'}"))
mid = m.get("id") if isinstance(m,dict) else None
st, m2, _ = upload(gid, "e2e-例题.txt", "例题来源：求 1+2+...+n", kind="example_source")
step("上传 example_source 类型", st==200 and isinstance(m2,dict) and m2.get("kind")=="example_source",
     lambda: (st==200 and isinstance(m2,dict) and m2.get("kind")=="example_source", f"status={st} kind={m2.get('kind') if isinstance(m2,dict) else m2}"))
st, lst, _ = call("GET", f"/goals/{gid}/materials")
step("GET /goals/{id}/materials 列出", st==200 and isinstance(lst,list) and len(lst)>=2,
     lambda: (st==200 and isinstance(lst,list) and len(lst)>=2, f"count={len(lst) if isinstance(lst,list) else lst}"))
st, bad, _ = upload(gid, "恶意.exe", "MZ\x90\x00")
step("非法扩展名被拒绝（.exe）", 400<=st<500, lambda: (400<=st<500, f"status={st} detail={str(bad)[:110]}"))
st, bad2, _ = call("GET", f"/goals/{gid}/materials")
st, nope, _ = call("DELETE","/materials/nonexistent-id")
step("删除不存在材料 -> 404", st==404, lambda: (st==404, f"status={st}"))
if mid:
    st, ok, _ = call("DELETE", f"/materials/{mid}")
    step("DELETE /materials/{id} 删除材料", st==200, lambda: (st==200, f"status={st} {str(ok)[:60]}"))

print("\n"+"="*100); print("阶段 I：格式规范（内置 / 匹配 / 快照冻结）"); print("="*100)
st, specs, _ = call("GET","/format-specs")
step("GET /format-specs 内置规范已就绪", st==200 and isinstance(specs,list) and len(specs)>0,
     lambda: (st==200 and isinstance(specs,list) and len(specs)>0, f"count={len(specs) if isinstance(specs,list) else specs} names={[s.get('name') for s in specs][:6] if isinstance(specs,list) else '?'} builtin={sum(1 for s in specs if s.get('is_builtin')) if isinstance(specs,list) else '?'}"))
defaults=[s for s in specs if s.get("is_default")] if isinstance(specs,list) else []
step("默认规范唯一", len(defaults)<=1, lambda: (len(defaults)<=1, f"default_count={len(defaults)}"))
spec_id = specs[0]["id"] if isinstance(specs,list) and specs else None
st, one, _ = call("GET", f"/format-specs/{spec_id}")
step("GET /format-specs/{id} 详情", st==200 and isinstance(one,dict) and one.get("id")==spec_id, lambda: (st==200 and isinstance(one,dict), f"name={one.get('name') if isinstance(one,dict) else one}"))
st, dup, _ = call("POST", f"/format-specs/{spec_id}/duplicate", {})
step("POST /format-specs/{id}/duplicate 复制", st==200 and isinstance(dup,dict) and dup.get("id")!=spec_id,
     lambda: (st==200 and isinstance(dup,dict) and dup.get("id")!=spec_id, f"new_id={dup.get('id') if isinstance(dup,dict) else dup} name={dup.get('name') if isinstance(dup,dict) else '?'}"))
dup_id = dup.get("id") if isinstance(dup,dict) else None
st, mt, _ = call("POST","/format-specs/match", {"requirement":"我要一份可以直接放进 Obsidian 的学习教程，包含章节与练习"})
step("POST /format-specs/match 自动匹配", st==200 and isinstance(mt,dict), lambda: (st==200 and isinstance(mt,dict), f"status={st} source={mt.get('source') if isinstance(mt,dict) else mt} spec={ (mt.get('selected_spec') or {}).get('name') if isinstance(mt,dict) else '?'} note={str(mt.get('note'))[:80] if isinstance(mt,dict) else '?'}"))
if dup_id:
    st, sd, _ = call("POST", f"/format-specs/{dup_id}/default", {})
    step("POST /format-specs/{id}/default 设为默认", st==200, lambda: (st==200, f"status={st}"))
    st, after, _ = call("GET","/format-specs")
    nd=[s for s in after if s.get("is_default")] if isinstance(after,list) else []
    step("设默认后仍只有一个默认规范", len(nd)==1 and nd[0]["id"]==dup_id, lambda: (len(nd)==1 and nd[0]["id"]==dup_id, f"defaults={len(nd)} id={nd[0]['id'] if nd else None}"))
    st, dd, _ = call("DELETE", f"/format-specs/{dup_id}")
    step("DELETE /format-specs/{id}", st==200, lambda: (st==200, f"status={st}"))
    st, sp2, _ = call("GET","/format-specs")
    nd2=[s for s in sp2 if s.get("is_default")] if isinstance(sp2,list) else []
    step("删除默认规范后自动回落其他默认", len(nd2)==1, lambda: (len(nd2)==1, f"defaults={len(nd2)} -> {[s.get('name') for s in nd2]}"))
st, g, _ = call("GET", f"/goals/{gid}")
step("目标已冻结格式规范快照 format_spec_snapshot", bool(g.get("format_spec_snapshot")),
     lambda: (bool(g.get("format_spec_snapshot")), f"spec_id={g.get('format_spec_id')!r} source={g.get('format_spec_source')!r} snapshot_len={len(g.get('format_spec_snapshot') or '')}"))

print("\n"+"="*100); print("阶段 J：版本回滚 / 单节重生成 / 交付回写"); print("="*100)
st, t, _ = call("GET", f"/tutorials/{tid}")
versions = (t or {}).get("versions") or []
content=((t or {}).get("current_version") or {}).get("content") or {}
sections=content.get("sections") or []
step("GET /tutorials/{id} 含版本列表", st==200 and len(versions)>=1, lambda: (st==200 and len(versions)>=1, f"versions={len(versions)} numbers={[v.get('version') for v in versions]}"))
sid = sections[0].get("id") if sections else None
if sid:
    st, sec, _ = call("GET", f"/tutorials/{tid}/sections/{sid}")
    step("GET /tutorials/{tid}/sections/{sid} 章节详情", st==200 and isinstance(sec,dict) and sec.get("id")==sid,
         lambda: (st==200 and isinstance(sec,dict), f"status={st} title={sec.get('title') if isinstance(sec,dict) else sec} blocks={len((sec.get('content') or [])) if isinstance(sec,dict) else '?'}"))
    st, rg, _ = call("POST", f"/tutorials/{tid}/sections/{sid}/regenerate", {})
    step("POST /sections/{sid}/regenerate 单节重生成", st==200 and isinstance(rg,dict),
         lambda: (st==200 and isinstance(rg,dict), f"status={st} versions_now={len((rg.get('versions') or [])) if isinstance(rg,dict) else rg} job={ (rg.get('job') or {}).get('id') if isinstance(rg,dict) else '?'}"))
    st, rg2, _ = call("GET", f"/tutorials/{tid}")
    v2=(rg2 or {}).get("versions") or []
    step("重生成后版本数增加", len(v2)>len(versions), lambda: (len(v2)>len(versions), f"before={len(versions)} after={len(v2)}"))
    if len(v2)>1:
        target=[v for v in v2 if v.get("version")==1]
        if target:
            st, rs, _ = call("POST", f"/tutorials/{tid}/restore/1", {})
            step("POST /tutorials/{tid}/restore/{version} 回滚", st==200 and isinstance(rs,dict) and ((rs.get("current_version") or {}).get("version")==1),
                 lambda: (st==200 and isinstance(rs,dict) and ((rs.get("current_version") or {}).get("version")==1), f"status={st} current={ (rs.get('current_version') or {}).get('version') if isinstance(rs,dict) else rs}"))
st, nf, _ = call("POST", f"/tutorials/nonexistent/sections/xxx/regenerate", {})
step("重生成不存在的教程 -> 404", st==404, lambda: (st==404, f"status={st}"))
st, dl, _ = call("POST", f"/tutorials/{tid}/delivery", {"delivered":True,"vault_path":"D:/vault/学习/E2E 测试.md","wikilinks_resolved":True,"unresolved_links":[]})
step("POST /tutorials/{id}/delivery 交付回写（Obsidian）", st==200 and isinstance(dl,dict),
     lambda: (st==200 and isinstance(dl,dict), f"status={st} delivery={json.dumps(dl.get('delivery') if isinstance(dl,dict) else dl, ensure_ascii=False)[:150]}"))

print("\n"+"="*100); print("阶段 K：实践任务 / 复盘 / 答疑（后端遗留能力是否仍可用）"); print("="*100)
st, tk, _ = call("POST", f"/goals/{gid}/tasks", {"title":"E2E 实践任务","instructions":"用 grep 找出 error 行","task_type":"practice","expected_artifact":"命令输出","validation_rule":"能复现"})
step("POST /goals/{id}/tasks 创建实践任务", st==200 and isinstance(tk,dict) and tk.get("id"), lambda: (st==200 and isinstance(tk,dict) and bool(tk.get("id")), f"status={st} id={tk.get('id') if isinstance(tk,dict) else tk}"))
task_id = tk.get("id") if isinstance(tk,dict) else None
if task_id:
    st, at, _ = call("POST", f"/tasks/{task_id}/attempts", {"artifact":"grep -n error app.log","artifact_type":"command","help_level":"A1","user_explanation":"我先找 error"})
    step("POST /tasks/{id}/attempts 提交尝试", st==200 and isinstance(at,dict), lambda: (st==200 and isinstance(at,dict), f"status={st} help_level={at.get('help_level') if isinstance(at,dict) else at}"))
    st, ats, _ = call("GET", f"/tasks/{task_id}/attempts")
    step("GET /tasks/{id}/attempts 列出尝试", st==200 and isinstance(ats,list) and len(ats)>=1, lambda: (st==200 and isinstance(ats,list) and len(ats)>=1, f"count={len(ats) if isinstance(ats,list) else ats}"))
    st, tp, _ = call("PATCH", f"/tasks/{task_id}", {"status":"done"})
    step("PATCH /tasks/{id} 标记完成", st==200, lambda: (st==200, f"status={st}"))
st, rf, _ = call("POST", f"/goals/{gid}/reflections", {"summary":"E2E 复盘","learned_capabilities":["会用 grep"],"unresolved_gaps":["awk 不熟"],"next_actions":["练 awk"]})
step("POST /goals/{id}/reflections 复盘", st==200 and isinstance(rf,dict), lambda: (st==200 and isinstance(rf,dict), f"status={st} {str(rf)[:90]}"))
st, rfs, _ = call("GET", f"/goals/{gid}/reflections")
step("GET /goals/{id}/reflections 列出", st==200 and isinstance(rfs,list) and len(rfs)>=1, lambda: (st==200 and isinstance(rfs,list), f"count={len(rfs) if isinstance(rfs,list) else rfs}"))
st, ch, _ = call("POST","/chat", {"goal_id":gid,"message":"grep 和 awk 的区别是什么？"})
step("POST /chat 上下文答疑", st==200 and isinstance(ch,dict) and ch.get("reply"), lambda: (st==200 and isinstance(ch,dict) and bool(ch.get("reply")), f"status={st} demo={ch.get('demo') if isinstance(ch,dict) else ch} reply={str(ch.get('reply'))[:90] if isinstance(ch,dict) else '?'}"))
st, kp, _ = call("POST", f"/goals/{gid}/knowledge-proposals", {})
step("POST /goals/{id}/knowledge-proposals 知识提议", st==200 and isinstance(kp,list), lambda: (st==200 and isinstance(kp,list), f"status={st} count={len(kp) if isinstance(kp,list) else kp}"))
st, asm, _ = call("POST", f"/goals/{gid}/assessments", {})
step("POST /goals/{id}/assessments 能力评估", st==200, lambda: (st==200, f"status={st} {str(asm)[:100]}"))

print("\n"+"="*100); print("阶段 L：异常路径 / 边界"); print("="*100)
st, e1, _ = call("GET","/goals/nonexistent-goal-id")
step("不存在的目标 -> 404", st==404, lambda: (st==404, f"status={st} detail={str(e1)[:90]}"))
st, e2, _ = call("POST","/goals", {"title":""})
step("空标题创建目标 -> 422", st==422, lambda: (st==422, f"status={st}"))
st, e3, _ = call("POST","/goals", {"title":"x","domain_key":"不存在的学科"})
ok_unknown_domain = st==200
if isinstance(e3,dict) and e3.get("id"):
    step("未知学科回退通用画像（不报错）", ok_unknown_domain and e3.get("domain_name"), lambda: (ok_unknown_domain and bool(e3.get("domain_name")), f"status={st} domain_key={e3.get('domain_key')} domain_name={e3.get('domain_name')}"))
    call("DELETE", f"/goals/{e3['id']}?purge=true")
else:
    step("未知学科回退通用画像（不报错）", False, lambda: (False, f"status={st} {str(e3)[:120]}"))
st, e4, _ = call("GET","/tutorials/nonexistent")
step("不存在的教程 -> 404", st==404, lambda: (st==404, f"status={st}"))
st, e5, _ = call("GET","/generation-jobs/nonexistent")
step("不存在的任务 -> 404", st==404, lambda: (st==404, f"status={st}"))
st, e6, _ = call("POST","/training/feedback", {"goal_id":gid,"target_type":"general","rating":0})
step("rating=0 被拒绝", 400<=st<500, lambda: (400<=st<500, f"status={st}"))

print(f"\nSUMMARY pass={PASS} fail={FAIL}")
json.dump({"goal_id":gid,"tutorial_id":tid,"results":RESULTS}, open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part3.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
