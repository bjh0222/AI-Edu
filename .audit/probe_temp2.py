import os, tempfile
print("tempfile.gettempdir() ->", tempfile.gettempdir())
print("tempfile.tempdir      ->", tempfile.tempdir)
print("candidate_dirs       ->", tempfile._candidate_tempdir_list() if hasattr(tempfile,"_candidate_tempdir_list") else "n/a")
for d in [os.environ.get("TEMP"), os.path.expanduser("~"), "C:\\Users\\BJH", os.path.abspath("."), os.path.abspath("data")]:
    if not d: continue
    p = os.path.join(d, "aiedu_w_probe.bin")
    try:
        with open(p,"wb") as f: f.write(b"x")
        os.remove(p); print(f"  WRITE OK    {d}")
    except Exception as e:
        print(f"  WRITE FAIL  {d}  {type(e).__name__}: {e}")
try:
    print("read cmd-created file:", open(os.path.join(os.environ["TEMP"],"aiedu_cross_probe.bin")).read().strip())
except Exception as e:
    print("read fail:", type(e).__name__, e)
