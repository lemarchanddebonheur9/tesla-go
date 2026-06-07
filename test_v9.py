#!/usr/bin/env python3
"""Test V9 Studio Quantique — lance un clip et streame la progression."""
import urllib.request, json, time

BASE = "http://127.0.0.1:8369"

# 1. Lance la génération
body = json.dumps({
    "prompt": "Tesla coil sparking cinematic dark background, slow motion",
    "intent": "studio"
}).encode()
req = urllib.request.Request(
    BASE + "/api/generate", data=body,
    headers={"Content-Type": "application/json"}
)
d = json.loads(urllib.request.urlopen(req).read())
job_id = d["job_id"]
print(f"✅ Job lancé : {job_id}  |  branche : {d['branch']}")
print("⏳ En attente de la première réponse SSE...\n")

# 2. Stream la progression
time.sleep(2)
url = BASE + "/stream/" + job_id
for raw in urllib.request.urlopen(url):
    line = raw.decode("utf-8").strip()
    if not line or line.startswith(":"):
        continue
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        ev = json.loads(line)
        status   = ev.get("status", "?")
        progress = ev.get("progress", 0)
        step     = ev.get("step", "")
        elapsed  = ev.get("elapsed", 0)
        result   = ev.get("result")
        error    = ev.get("error")
        print(f"[{elapsed:>6.1f}s] {status:8} {progress:3}%  {step}")
        if result:
            print(f"\n🎬 CLIP PRÊT → {result}")
            break
        if error and status == "error":
            print(f"\n⚠  Erreur : {error}")
            # Le fallback continue côté serveur — on continue à lire
    except json.JSONDecodeError:
        pass
