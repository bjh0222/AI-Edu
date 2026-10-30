# -*- coding: utf-8 -*-
import json,sys,urllib.request,urllib.error
sys.stdout.reconfigure(encoding="utf-8")
B="http://127.0.0.1:8199/api"
def call(m,p,b=None):
    d=json.dumps(b,ensure_ascii=False).encode() if b is not None else None
    h={"Content-Type":"application/json"} if d else {}
    req=urllib.request.Request(B+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(req,timeout=300) as r:
            x=r.read(); return r.status,(json.loads(x.decode()) if x else None)
    except urllib.error.HTTPError as e:
        x=e.read()
        try: return e.code,json.loads(x.decode())
        except Exception: return e.code,x[:200].decode("utf-8","replace")
st,g,_=call("POST","/goals",{"title":"M6 复核目标","domain_key":"cs_it","motivation":"复核","application_context":"复核"}),None,None
st,g=call("POST","/goals",{"title":"M6 复核目标","domain_key":"cs_it","motivation":"复核","application_context":"复核"})
gid=g["id"]
print("goal:",gid)
st,d=call("POST",f"/goals/{gid}/diagnose")
st,t=call("POST",f"/goals/{gid}/tutorials/quickstart",{})
tid=(t.get("tutorial") or {}).get("id") if isinstance(t,dict) else None
print("tutorial:",tid)
print()
print("--- PATCH /reflections 真实返回 ---")
st,rf=call("POST",f"/goals/{gid}/reflections",{"summary":"原始复盘","learned_capabilities":"a","unresolved_gaps":"b","next_actions":"c"})
rid=rf["id"]
st,rp=call("PATCH",f"/reflections/{rid}",{"summary":"修订后的复盘"})
print("PATCH ->",st,json.dumps(rp,ensure_ascii=False))
st,lst=call("GET",f"/goals/{gid}/reflections")
print("GET list -> summary now:", repr(lst[0]["summary"]) if lst else "EMPTY")
print("=> 修订是否真的落库:", lst and lst[0]["summary"]=="修订后的复盘")
print()
print("--- POST /chat 真实返回 ---")
st,ch=call("POST","/chat",{"goal_id":gid,"tutorial_id":tid,"question":"grep 和 awk 的区别？"})
print("chat status:",st)
print("keys:",list(ch.keys()) if isinstance(ch,dict) else ch)
if isinstance(ch,dict):
    a=ch.get("assistant") or {}
    u=ch.get("user") or {}
    print("user.role:",u.get("role"),"len(content):",len(u.get("content") or ""))
    print("assistant.role:",a.get("role"),"len(content):",len(a.get("content") or ""))
    print("assistant.content preview:",repr((a.get("content") or "")[:300]))
    print("demo:",ch.get("demo"))
    print("=> 答疑返回非空回复:", bool((a.get("content") or "").strip()))
print()
print("--- 会话是否持久化（ChatMessage 落库）---")
st,ch2=call("POST","/chat",{"goal_id":gid,"question":"第二个问题"})
print("second chat ok:",st==200)
call("DELETE",f"/goals/{gid}?purge=true")
