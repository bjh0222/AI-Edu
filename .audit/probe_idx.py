import sqlite3, os, shutil, tempfile, time
tmp = tempfile.mkdtemp(prefix="idxtest_", dir=os.path.abspath("."))
db = os.path.join(tmp, "copy.db")
shutil.copy2("data/aiedu.db", db)
BIG = """SELECT id, source_type, feature, goal_id, tutorial_id, section_id, system_prompt, user_prompt,
 output_text, model_provider, model_name, prompt_tokens, completion_tokens, total_tokens, usage_source,
 rating, tags, comment, context_json, created_at FROM training_records"""
def run(label, sql, pragma=None):
    c = sqlite3.connect(db)
    if pragma: c.execute(pragma)
    t0=time.time()
    try:
        n=len(c.execute(sql).fetchall()); print(f"  OK    {label:46} rows={n:5} {time.time()-t0:.3f}s")
    except Exception as e:
        print(f"  FAIL  {label:46} {type(e).__name__}: {e}")
    c.close()
print("=== BEFORE index (default temp dir, no temp_store) ===")
run("records DESC LIMIT 50", BIG + " ORDER BY created_at DESC LIMIT 50 OFFSET 0")
run("export ASC (all rows)", BIG + " ORDER BY created_at ASC")
print("=== EXPLAIN QUERY PLAN before ===")
c=sqlite3.connect(db)
for r in c.execute("EXPLAIN QUERY PLAN " + BIG + " ORDER BY created_at DESC LIMIT 50"): print("   ", r)
c.close()
print("=== CREATE INDEX on created_at ===")
c=sqlite3.connect(db); c.execute("CREATE INDEX ix_training_records_created_at ON training_records (created_at)"); c.commit(); c.close()
print("=== AFTER index ===")
run("records DESC LIMIT 50", BIG + " ORDER BY created_at DESC LIMIT 50 OFFSET 0")
run("export ASC (all rows)", BIG + " ORDER BY created_at ASC")
print("=== EXPLAIN QUERY PLAN after ===")
c=sqlite3.connect(db)
for r in c.execute("EXPLAIN QUERY PLAN " + BIG + " ORDER BY created_at DESC LIMIT 50"): print("   ", r)
c.close()
shutil.rmtree(tmp, ignore_errors=True)
