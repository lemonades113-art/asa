import json, sys, glob, os

results_dir = r"c:\Users\111\Desktop\简历\三个\ASA\evaluation_results"
files = sorted(glob.glob(os.path.join(results_dir, "real_eval_*.json")), key=os.path.getmtime, reverse=True)

if not files:
    print("No result files found.")
    sys.exit(1)

latest = files[0]
print("Latest file:", os.path.basename(latest))

with open(latest, encoding="utf-8") as f:
    data = json.load(f)

# Support both old format (e2e_results) and new format (e2e.per_case)
e2e_list = data.get("e2e_results", [])
if not e2e_list and "e2e" in data:
    e2e_obj = data["e2e"]
    e2e_list = e2e_obj.get("per_case", [])
    summary = e2e_obj.get("summary", {})
else:
    summary = data.get("e2e_summary", {})

print("E2E cases:", len(e2e_list), "\n")
for i, r in enumerate(e2e_list):
    status = "PASS" if r.get("pass") or r.get("success") else "FAIL"
    diff = r.get("difficulty", "?")
    query = r.get("query", "")[:45]
    has_data = r.get("has_data", 0)
    kw = r.get("kw_recall", 0)
    lat_ms = r.get("latency_ms", 0)
    lat_s = r.get("latency_s", lat_ms / 1000 if lat_ms else 0)
    print("[%02d] %s [%s] %s | data=%s kw=%.2f lat=%.1fs" % (i+1, status, diff, query, int(bool(has_data)), kw, lat_s))

if summary:
    pa1 = summary.get("pass_at_1", summary.get("pass_rate", "N/A"))
    passed = summary.get("passed", "?")
    total = summary.get("total", "?")
    avg_lat = summary.get("avg_latency_s", "?")
    print("\nPass@1 =", pa1, " (%s/%s)  avg_lat=%.1fs" % (passed, total, avg_lat if isinstance(avg_lat, float) else 0))
else:
    passed = sum(1 for r in e2e_list if r.get("pass") or r.get("success"))
    total = len(e2e_list)
    pa1 = passed/total if total else 0
    print("\nPass@1 = %.2f  (%d/%d)" % (pa1, passed, total))
