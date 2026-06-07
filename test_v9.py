#!/usr/bin/env python3
"""Test V9 Studio Quantique — lance un clip et streame la progression."""
import urllib.request, json, time, sys

BASE = "http://127.0.0.1:8369"

# Intent configurable : python test_v9.py image | fast | studio | cinematic
INTENT = sys.argv[1] if len(sys.argv) > 1 else "studio"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else "Tesla coil sparking gold energy cinematic dark background"

print(f"🎬 Intent: {INTENT}  |  Prompt: {PROMPT[:60]}")

# 1. Lance la génération
body = json.dumps({"prompt": PROMPT, "intent": INTENT}).encode()
req = urllib.request.Request(
    BASE + "/api/generate", data=body,
    headers={"Content-Type": "application/json"}
)
d = json.loads(urllib.request.urlopen(req).read())
job_id = d["job_id"]
print(f"✅ Job lancé : {job_id}  |  branche : {d['branch']}\n")

# 2. Stream la progression
time.sleep(2)
url = BASE + "/stream/" + job_id
prev_step = ""
for raw in urllib.request.urlopen(url):
    line = raw.decode("utf-8").strip()
    if not line or line.startswith(":"): continue
    if line.startswith("data:"): line = line[5:].strip()
    try:
        ev = json.loads(line)
        status   = ev.get("status", "?")
        progress = ev.get("progress", 0)
        step     = ev.get("step", "")
        elapsed  = ev.get("elapsed", 0)
        result   = ev.get("result")
        error    = ev.get("error")

        if step != prev_step or status in ("done", "error"):
            print(f"[{elapsed:>6.1f}s] {status:8} {progress:3}%  {step or error or ''}")
            prev_step = step

        if result:
            print(f"\n🎬 CLIP PRÊT → ouvre dans le navigateur :\n{result}")
            break
        if status == "error" and not step:
            print(f"\n❌ Erreur finale : {error}")
            break
    except json.JSONDecodeError:
        pass
