import os, tempfile
t = os.path.join(os.environ["TEMP"], "aiedu_py_probe.bin")
try:
    open(t, "wb").write(b"x"); os.remove(t); print("py write TEMP: OK")
except Exception as e:
    print("py write TEMP: FAIL", type(e).__name__, e)
print("TEMP =", os.environ["TEMP"])
print("cwd  =", os.getcwd())
