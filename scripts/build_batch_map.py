import json, re, csv, sys
d = sys.argv[1]
em = json.load(open(d+"/PRD-Retrieve All Event Managers.json"))["records"]
ev = json.load(open(d+"/PRD-Retrieve All Batch Events.json"))
tk = {t["id"]: t for t in json.load(open(d+"/PRD-Retrieve All Batch Tasks.json"))}
em = [e for e in em if re.match(r"(USM|MW) ", e["eventMgrTaskName"])]
rows = []
for e in em:
    norm = re.sub(r"\s*-\s*[\d:]+\s*[AP]M Mountain$", "", e["eventMgrTaskName"])
    cands = [b for b in ev if b["name"] == norm] or [b for b in ev if b["name"].startswith(norm)]
    conf = "Exact" if len(cands) == 1 and cands[0]["name"] == norm else ("Prefix" if len(cands) == 1 else ("Ambiguous" if cands else "No match"))
    if not cands: cands = [None]
    for b in cands:
        tasks = b["batchEventTasks"] if b else [None]
        for bt in tasks:
            t = tk.get(bt["id"]) if bt else None
            items = t["batchTaskItems"] if t else [None]
            for i in items:
                rows.append({
                    "EM Id": e["eventManagerId"], "Event Manager Name": e["eventMgrTaskName"], "EM Status": e["status"],
                    "Match": conf,
                    "Batch Event Id": b["id"] if b else "", "Batch Event Name": b["name"] if b else "",
                    "Batch Task Id": bt["id"] if bt else "", "Batch Task Name": t["name"] if t else "",
                    "Seq": i["sequenceNumber"] if i else "",
                    "actionName": i["actionName"]["qualifier"] if i else "",
                    "actionType": i["actionType"]["qualifier"] if i else "",
                    "parameterString": i["parameterString"] if i else "",
                })
rows.sort(key=lambda r: (r["EM Id"], r["Batch Event Id"] if r["Batch Event Id"] != "" else 0))
cols = list(rows[0].keys())
with open(d+"/EventManager_BatchEvent_Task_Actions_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
# summary: one row per EM/event/task/actionName/actionType with params collapsed
summ = {}
for r in rows:
    k = tuple(r[c] for c in cols[:8]) + (r["actionName"], r["actionType"])
    summ.setdefault(k, []).append(r["parameterString"])
def fmt(p):
    if len(p) > 4: return f"{p[0]} ... {p[-1]} ({len(p)} items)"
    return "; ".join(p)
with open(d+"/EventManager_BatchEvent_Task_Actions_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(cols[:8] + ["actionName", "actionType", "parameterString(s)"])
    for k, p in summ.items(): w.writerow(list(k) + [fmt(p)])
print(len(rows), "detail rows;", len(summ), "summary rows")
for k, p in summ.items(): print(" | ".join(map(str, k)), "|", fmt(p))
