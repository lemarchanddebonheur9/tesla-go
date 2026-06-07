#!/usr/bin/env python3
"""
MERCREDIS TESLA — Épisode 1
"Les Signaux de Mars Étaient Jupiter"
→ /api/compose : TTS Henri + clips vidéo → MP4 final
"""
import urllib.request, json, time

BASE  = "http://127.0.0.1:8369"
VOICE = "fr-FR-HenriNeural"

SEGMENTS = [
    {
        "text":     "Nelly, l'expérience de Tesla est terminée. Et les résultats sont étonnants...",
        "prompt":   "aerial view of Colorado Springs 1899, vintage sepia, mountains, cinematic",
        "duration": 7,
        "intent":   "image",
    },
    {
        "text":     "Tesla capte des signaux rythmiques qu'il croit venir de Mars.",
        "prompt":   "Nikola Tesla leaning over electrical apparatus, laboratory, dramatic lighting, cinematic",
        "duration": 7,
        "intent":   "image",
    },
    {
        "text":     "Mais ce n'était pas la réalité. Les signaux n'étaient pas d'origine martienne.",
        "prompt":   "animated radio signals in space, glowing lines, dark background, cinematic",
        "duration": 7,
        "intent":   "image",
    },
    {
        "text":     "Mais Jupiter, en fait.",
        "prompt":   "planet Jupiter with colorful cloud bands, space, epic cinematic view",
        "duration": 7,
        "intent":   "image",
    },
    {
        "text":     "La radioastronomie a révélé que les signaux étaient en fait des émissions radio naturelles de Jupiter.",
        "prompt":   "radio telescope observatory at night, star trails, data visualization, cinematic",
        "duration": 8,
        "intent":   "image",
    },
    {
        "text":     "Science-fiction devenant science. L'esprit d'exploration de Tesla a ouvert la voie à de nouvelles découvertes.",
        "prompt":   "futuristic energy field transforming into reality, gold cyan light, cinematic",
        "duration": 8,
        "intent":   "image",
    },
    {
        "text":     "Nelly, nous avons une nouvelle découverte à faire. La suivante est à nous.",
        "prompt":   "aerial view Colorado Springs night sky, stars, electricity, cinematic",
        "duration": 7,
        "intent":   "image",
    },
    {
        "text":     "Les signaux de Mars n'étaient que le début d'une nouvelle aventure dans l'espace.",
        "prompt":   "night sky stars and planets glowing, milky way, epic wide angle cinematic",
        "duration": 20,
        "intent":   "image",
    },
]

print(f"🎬 MERCREDIS TESLA — Épisode 1")
print(f"   {len(SEGMENTS)} segments · voix {VOICE}\n")

body = json.dumps({"segments": SEGMENTS, "voice": VOICE}).encode()
req  = urllib.request.Request(
    BASE + "/api/compose", data=body,
    headers={"Content-Type": "application/json"}
)
d = json.loads(urllib.request.urlopen(req).read())
job_id = d["job_id"]
print(f"✅ Job compose lancé : {job_id}\n")

url = BASE + "/compose/" + job_id
prev = ""
for raw in urllib.request.urlopen(url):
    line = raw.decode("utf-8").strip()
    if not line or line.startswith(":"): continue
    if line.startswith("data:"): line = line[5:].strip()
    try:
        ev = json.loads(line)
        step   = ev.get("step", "")
        status = ev.get("status", "")
        prog   = ev.get("progress", 0)
        result = ev.get("result")
        error  = ev.get("error")
        if step != prev or status in ("done", "error"):
            print(f"  [{prog:3}%] {step or status}")
            prev = step
        if result:
            print(f"\n🎬 ÉPISODE PRÊT → ouvre dans le navigateur :\n{result}\n")
            break
        if status == "error" and not step:
            print(f"\n❌ {error}")
            break
    except json.JSONDecodeError:
        pass
