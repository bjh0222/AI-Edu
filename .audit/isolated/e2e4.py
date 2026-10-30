# -*- coding: utf-8 -*-
"""阶段 M：按真实 schema 复测此前失败的 5 项 + 版本回滚链路 + 孤儿端点核查"""
import json, sys, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
B="http://127.0.0.1:8199/api"
def call(m,p,body=None,raw=False,timeout=600):
    data=None; h={}
    if body is not None:
        data=json.dumps(body,ensure_ascii=False).encode(); h["Content-Type"]="application/json"
    req=urllib.request.Request(B+p,data=data,headers=h,method=m)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            b=r.read()
            return (r.status,b,dict(r.headers)) if raw else (r.status,(json.loads(b.decode()) if b else None),dict(r.headers))
    except urllib.error.HTTPError as e:
        b=e.read()
        try: return e.code,json.loads(b.decode()),{}
        except Exception: return e.code,b[:300].decode("utf-8","replace"),{}
P=F=0
def step(n, ok, detail):
    global P,F
    if ok: P+=1
    else: F+=1
    print(("PASS  " if ok else "FAIL  ")+f"{n:54} {str(detail)[:210]}")
prev=json.load(open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part3.json",encoding="utf-8"))
gid,tid=prev["goal_id"],prev["tutorial_id"]

print("="*104)
print("M1. 交付回写（按 Obsidian 插件真实载荷 status/path/version）")
print("="*104)
st,t,_=call("GET",f"/tutorials/{tid}")
cur_ver=((t or {}).get("current_version") or {}).get("version") or 0
st,dl,_=call("POST",f"/tutorials/{tid}/delivery",{"status":"delivered","path":"D:/vault/学习/E2E-教程.md","version":cur_ver})
step("POST /delivery 交付回写（真实载荷）", st==200 and isinstance(dl,dict) and dl.get("delivery_status")=="delivered",
     f"status={st} delivery_status={dl.get('delivery_status') if isinstance(dl,dict) else dl} path={dl.get('delivery_path') if isinstance(dl,dict) else '?'} ver={dl.get('delivery_version') if isinstance(dl,dict) else '?'}")
st,dl2,_=call("POST",f"/tutorials/{tid}/delivery",{"status":"failed","path":"","version":0})
step("POST /delivery 失败状态回写", st==200 and isinstance(dl2,dict) and dl2.get("delivery_status")=="failed",
     f"status={st} delivery_status={dl2.get('delivery_status') if isinstance(dl2,dict) else dl2}")
st,dl3,_=call("POST",f"/tutorials/{tid}/delivery",{"status":"bogus"})
step("非法 delivery.status 被拒绝", 400<=st<500, f"status={st}")
call("POST",f"/tutorials/{tid}/delivery",{"status":"delivered","path":"D:/vault/学习/E2E-教程.md","version":cur_ver})

print()
print("="*104); print("M2. 复盘 / 答疑（按真实 schema：字段是字符串、问题字段叫 question）"); print("="*104)
st,rf,_=call("POST",f"/goals/{gid}/reflections",{"summary":"E2E 复盘：掌握了 grep 基本用法","learned_capabilities":"能用 grep 定位错误行","unresolved_gaps":"awk 字段处理不熟","next_actions":"补练 awk"})
step("POST /reflections（字符串字段）", st==200 and isinstance(rf,dict) and rf.get("summary"),
     f"status={st} id={rf.get('id') if isinstance(rf,dict) else rf} summary={str(rf.get('summary'))[:40] if isinstance(rf,dict) else '?'}")
st,rfs,_=call("GET",f"/goals/{gid}/reflections")
step("GET /reflections 列出", st==200 and isinstance(rfs,list) and len(rfs)>=1, f"count={len(rfs) if isinstance(rfs,list) else rfs}")
rf_id = rfs[0]["id"] if isinstance(rfs,list) and rfs else None
if rf_id:
    st,rp,_=call("PATCH",f"/reflections/{rf_id}",{"summary":"E2E 复盘（已修订）"})
    step("PATCH /reflections/{id}", st==200 and isinstance(rp,dict) and rp.get("summary")=="E2E 复盘（已修订）", f"status={st} summary={rp.get('summary') if isinstance(rp,dict) else rp}")
st,ch,_=call("POST","/chat",{"goal_id":gid,"tutorial_id":tid,"question":"grep 和 awk 的区别是什么？"})
step("POST /chat（字段名 question）", st==200 and isinstance(ch,dict), f"status={st} keys={list(ch.keys()) if isinstance(ch,dict) else ch} demo={ch.get('demo') if isinstance(ch,dict) else '?'}")
if isinstance(ch,dict):
    msgs=ch.get("messages") or []
    asst=[m for m in msgs if m.get("role")=="assistant"]
    step("答疑返回 assistant 回复且非空", bool(asst) and bool(asst[-1].get("content")), f"messages={len(msgs)} assistant_content_len={len(asst[-1].get('content') or '') if asst else 0} preview={str(asst[-1].get('content'))[:80] if asst else 'NONE'}")
st,ch2,_=call("POST","/chat",{"goal_id":gid,"question":""})
step("空问题被拒绝（question min_length=1）", 400<=st<500, f"status={st}")

print()
print("="*104); print("M3. 版本回滚链路（restore/{version}）"); print("="*104)
st,t,_=call("GET",f"/tutorials/{tid}")
hc=(t or {}).get("history_count")
step("教程暴露 history_count（版本数）", isinstance(hc,int) and hc>=1, f"history_count={hc} status={st}")
sid=((((t or {}).get("current_version") or {}).get("content") or {}).get("sections") or [{}])[0].get("id")
if sid:
    st,rg,_=call("POST",f"/tutorials/{tid}/sections/{sid}/regenerate",{})
    st,t2,_=call("GET",f"/tutorials/{tid}")
    hc2=(t2 or {}).get("history_count")
    step("单节重生成后 history_count 增加", isinstance(hc2,int) and hc2>hc, f"before={hc} after={hc2}")
    cv=((t2 or {}).get("current_version") or {}).get("version")
    step("current_version 版本号递增", isinstance(cv,int) and cv>=hc2, f"current_version={cv} history_count={hc2}")
    st,rs,_=call("POST",f"/tutorials/{tid}/restore/1",{})
    ok_restore = st==200 and isinstance(rs,dict) and ((rs.get("current_version") or {}).get("version")==1)
    step("POST /restore/1 回滚到 v1", ok_restore, f"status={st} current={ (rs.get('current_version') or {}).get('version') if isinstance(rs,dict) else rs} history={(rs or {}).get('history_count') if isinstance(rs,dict) else '?'}")
    st,rs2,_=call("POST",f"/tutorials/{tid}/restore/9999",{})
    step("回滚到不存在的版本 -> 4xx", 400<=st<500, f"status={st} detail={str(rs2)[:100]}")

print()
print("="*104); print("M4. 孤儿端点核查（后端有、前端/插件都不调）"); print("="*104)
ORPHAN_CANDIDATES = [
 "/goals/{gid}/tasks","/tasks/{task_id}/attempts","/goals/{gid}/assessments","/goals/{gid}/reflections",
 "/reflections/{rid}","/chat","/goals/{gid}/knowledge-proposals","/knowledge/proposals/{pid}/review",
 "/tutorials/{tid}/restore/{version}","/knowledge/dedupe","/knowledge/extract/{tid}","/knowledge/graph",
]
print("候选（仅供人工判断，见 PROJECT_AUDIT.md）：")
for c in ORPHAN_CANDIDATES: print("   ", c)

print()
print("="*104); print("M5. 导出 / 导入 / 彻底删除（含 JSON 备份落盘）"); print("="*104)
st,body,hdrs=call("GET","/export",raw=True)
exp=json.loads(body.decode()) if st==200 else None
step("GET /export 全量备份", st==200 and isinstance(exp,dict) and exp.get("version")==1 and "data" in exp,
     f"status={st} version={exp.get('version') if isinstance(exp,dict) else '?'} tables={len(exp.get('data') or {}) if isinstance(exp,dict) else '?'} bytes={len(body)}")
st,ii,_=call("POST","/import",{"version":99,"data":{}})
step("导入非 version=1 被拒绝", st==400, f"status={st} detail={str(ii)[:90]}")
st,ii2,_=call("POST","/import",{"version":1,"data":{"learning_goals":"not-a-list"}})
step("导入非法结构被拒绝", st==400, f"status={st}")
st,ii3,_=call("POST","/import",{"version":1,"data":{"learning_goals":[{"no_id":1}]}})
step("导入缺 id 记录被拒绝", st==400, f"status={st} detail={str(ii3)[:90]}")
st,kn,_=call("GET","/knowledge")
n_concepts=len((kn or {}).get("concepts") or []) if isinstance(kn,dict) else 0
st,kb,_=call("POST","/import",{"version":1,"data":{}})
step("知识数据安全阀：空备份导入被 409 阻止", st==409,
     f"status={st} current_concepts={n_concepts} detail={str(kb)[:140]}")
st,kg,_=call("GET","/knowledge")
n_after=len((kg or {}).get("concepts") or []) if isinstance(kg,dict) else -1
step("安全阀生效：知识网络未被清空", n_after==n_concepts and n_concepts>0, f"before={n_concepts} after={n_after}")

st,g,_=call("GET",f"/goals/{gid}")
step("彻底删除前目标存在", st==200, f"status={st} title={g.get('title') if isinstance(g,dict) else g}")
st,pur,_=call("DELETE",f"/goals/{gid}?purge=true")
step("DELETE /goals/{id}?purge=true 彻底删除", st==200 and isinstance(pur,dict) and pur.get("ok"),
     f"status={st} {str(pur)[:200]}")
import os
bp = pur.get("backup_path") if isinstance(pur,dict) else None
step("删除前已写 JSON 备份", bool(bp) and os.path.exists(bp), f"backup={bp} exists={os.path.exists(bp) if bp else False}")
st,g2,_=call("GET",f"/goals/{gid}")
step("删除后目标 404", st==404, f"status={st}")
st,tt,_=call("GET",f"/tutorials/{tid}")
step("删除后教程一并移除", st==404, f"status={st}")
st,g3,_=call("GET","/goals?include_archived=true")
step("目标不再出现在列表（含归档）", isinstance(g3,list) and not any(x.get("id")==gid for x in g3), f"remaining={len(g3) if isinstance(g3,list) else g3}")
st,arch,_=call("POST","/goals",{"title":"归档测试目标","domain_key":"cs_it"})
aid=arch.get("id") if isinstance(arch,dict) else None
st,ar,_=call("DELETE",f"/goals/{aid}")
step("DELETE /goals/{id}（软归档）", st==200, f"status={st} {str(ar)[:80]}")
st,l1,_=call("GET","/goals")
st,l2,_=call("GET","/goals?include_archived=true")
step("归档后默认列表隐藏、include_archived 可见",
     isinstance(l1,list) and not any(x.get("id")==aid for x in l1) and isinstance(l2,list) and any(x.get("id")==aid for x in l2),
     f"default={len(l1) if isinstance(l1,list) else '?'} with_archived={len(l2) if isinstance(l2,list) else '?'}")
call("DELETE",f"/goals/{aid}?purge=true")

print(f"\nSUMMARY pass={P} fail={F}")
json.dump({"goal_id":gid,"tutorial_id":tid,"pass":P,"fail":F}, open(r"D:\桌面\dsh\ai-edu\.audit\isolated\e2e_part4.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
