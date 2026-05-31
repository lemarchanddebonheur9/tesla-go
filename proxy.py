#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  ETHV_APP_TESLAGO_PROXY_V8_PARALLEL_2026-05-30.py
================================================================================
  ⚡ TESLA GO V8 — Console de Production Parallèle — 100% Gratuit
  Endpoints HF Spaces VÉRIFIÉS · Téléchargement immédiat · SSE robuste

  Auteur    : Lolo (Laurent Becker) — LMDB17 / etheravolt.fr
  Port      : 8369 (constante TNT)
  Signature : Tik Tik Tik — Le UN ⚡

  BRANCHES CONFIRMÉES (endpoints vérifiés en live)
  ─────────────────────────────────────────────────
  pollinations-img  → image.pollinations.ai          ✅ sans clé
  pollinations-vid  → gen.pollinations.ai/v1/video   ✅ alpha
  cogvideox         → zai-org/CogVideoX-2B-Space     ✅ /generate
  animatediff       → ByteDance/AnimateDiff-Lightning ✅ /generate_image
  wan22             → Wan-AI/Wan-2.2-5B              ⚠  nécessite HF_TOKEN valide
  ltx               → Lightricks/LTX-Video            ⚠  nécessite HF_TOKEN valide

  CORRECTIONS CRITIQUES V8.1
  ──────────────────────────
  [1] Noms d'API réels vérifiés via client.view_api()
  [2] Résultats copiés dans outputs/ immédiatement (évite expiration HF)
  [3] Reconnexion SSE automatique côté frontend
  [4] Fallback automatique si branche échoue
================================================================================
"""

import os, json, uuid, asyncio, logging, time, shutil
from pathlib import Path
from datetime import datetime

import aiohttp
from aiohttp import web

try:
    from gradio_client import Client, handle_file
    HAS_GRADIO = True
except ImportError:
    HAS_GRADIO = False
    print("⚠  pip install gradio_client")

# ── Config ────────────────────────────────────────────────────────────────────
PORT     = 8369
HOST     = "127.0.0.1"
HF_TOKEN = os.environ.get("HF_TOKEN", "")
OUTPUTS  = Path(__file__).parent / "outputs"
OUTPUTS.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("teslago")

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# ── State global ──────────────────────────────────────────────────────────────
SESSIONS = {}
CLIPS    = {}

# Semaphores par branche
SEMS = {
    "pollinations-img": asyncio.Semaphore(10),
    "pollinations-vid": asyncio.Semaphore(5),
    "cogvideox":        asyncio.Semaphore(3),
    "animatediff":      asyncio.Semaphore(3),
    "wan22":            asyncio.Semaphore(2),
    "ltx":              asyncio.Semaphore(2),
    "svd":              asyncio.Semaphore(2),
    "local":            asyncio.Semaphore(1),
}

# Ordre de fallback si une branche échoue
FALLBACK = {
    "wan22":      "cogvideox",
    "ltx":        "cogvideox",
    "cogvideox":  "animatediff",
    "animatediff":"pollinations-vid",
    "svd":        "pollinations-vid",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════════════════════════════════════════════

def new_clip(session_id, prompt, branch, intent, index):
    cid = f"{session_id[:4]}-{index:02d}-{uuid.uuid4().hex[:4]}"
    CLIPS[cid] = {
        "id": cid, "session_id": session_id, "index": index,
        "prompt": prompt, "branch": branch, "intent": intent,
        "status": "queued", "progress": 0, "step": "",
        "result": None, "error": None,
        "started_at": None, "elapsed": 0,
        "created": datetime.now().isoformat(),
    }
    return cid


def upd(cid, **kw):
    if cid in CLIPS:
        CLIPS[cid].update(kw)
        if CLIPS[cid].get("started_at"):
            CLIPS[cid]["elapsed"] = round(time.time() - CLIPS[cid]["started_at"], 1)


def cleanup_old_clips(max_sessions=50):
    """Purge sessions/clips les plus anciens au-delà de max_sessions."""
    if len(SESSIONS) <= max_sessions:
        return
    sorted_sessions = sorted(SESSIONS.values(), key=lambda s: s["created"])
    for s in sorted_sessions[:len(SESSIONS) - max_sessions]:
        for cid in s.get("clip_ids", []):
            CLIPS.pop(cid, None)
        SESSIONS.pop(s["id"], None)


async def tick_loop(cid, start):
    """Met à jour elapsed chaque seconde pendant l'exécution."""
    while CLIPS.get(cid, {}).get("status") == "running":
        CLIPS[cid]["elapsed"] = round(time.time() - start, 1)
        await asyncio.sleep(1)


def save_to_outputs(src_path: str, ext: str = ".mp4") -> str:
    """
    CORRECTION CRITIQUE [2] : copie immédiate dans outputs/.
    Les fichiers gradio_client sont dans /tmp et expirent vite.
    Retourne l'URL locale servable par Tesla Go.
    """
    fname  = f"{uuid.uuid4().hex[:12]}{ext}"
    dest   = OUTPUTS / fname
    try:
        shutil.copy2(src_path, dest)
        return f"http://127.0.0.1:{PORT}/outputs/{fname}"
    except Exception as e:
        log.error(f"Copie outputs/ échouée : {e}")
        return src_path   # fallback : chemin brut


def extract_video_path(result) -> str | None:
    """
    CORRECTION CRITIQUE [1] : gère les différents formats de retour HF Spaces.
    - CogVideoX : tuple → result[0] = dict(video=filepath)
    - AnimateDiff : dict → result["video"] = filepath
    - Direct str : chemin brut
    """
    if result is None:
        return None
    # Tuple (CogVideoX retourne 3 valeurs)
    if isinstance(result, (list, tuple)):
        result = result[0]
    # Dict avec clé "video"
    if isinstance(result, dict):
        return result.get("video") or result.get("path")
    # String directe
    if isinstance(result, str):
        return result
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  GÉNÉRATEURS — ENDPOINTS VÉRIFIÉS
# ═══════════════════════════════════════════════════════════════════════════════

async def gen_pollinations_image(cid, prompt, model="flux",
                                  width=1024, height=1024):
    """✅ Confirmé — aucune clé requise."""
    import urllib.parse
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Génération image Pollinations…", progress=10)
    tick = asyncio.create_task(tick_loop(cid, t))
    try:
        url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
               f"?model={model}&width={width}&height={height}&seed=369&nologo=true")
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=45)) as r:
                if r.status == 200:
                    # Sauvegarder l'image localement
                    fname = f"{uuid.uuid4().hex[:12]}.jpg"
                    dest  = OUTPUTS / fname
                    dest.write_bytes(await r.read())
                    local_url = f"http://127.0.0.1:{PORT}/outputs/{fname}"
                    upd(cid, progress=100, step="Image prête ✓",
                        status="done", result=local_url)
                else:
                    raise RuntimeError(f"Pollinations HTTP {r.status}")
    except Exception as e:
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


async def gen_pollinations_video(cid, prompt):
    """✅ Alpha — Seedance gratuit via Pollinations."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Envoi vers Pollinations Vidéo…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))
    try:
        upd(cid, progress=20, step="Génération Seedance en cours…")
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://gen.pollinations.ai/v1/video",
                json={"prompt": prompt, "model": "seedance", "ratio": "16:9"},
                timeout=aiohttp.ClientTimeout(total=240)
            ) as r:
                upd(cid, progress=80, step="Finalisation vidéo…")
                if r.status == 200:
                    data = await r.json()
                    video_url = data.get("url")
                    if video_url:
                        # Download and save locally
                        async with s.get(video_url, timeout=aiohttp.ClientTimeout(total=120)) as vr:
                            if vr.status == 200:
                                fname = f"{uuid.uuid4().hex[:12]}.mp4"
                                dest = OUTPUTS / fname
                                dest.write_bytes(await vr.read())
                                local_url = f"http://127.0.0.1:{PORT}/outputs/{fname}"
                                upd(cid, progress=100, step="Vidéo prête ✓",
                                    status="done", result=local_url)
                            else:
                                upd(cid, progress=100, step="Vidéo prête ✓",
                                    status="done", result=video_url)  # fallback: external URL
                    else:
                        raise RuntimeError("Pollinations vidéo: URL manquante dans la réponse")
                else:
                    raise RuntimeError(f"Pollinations vidéo HTTP {r.status}")
    except Exception as e:
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


def _call_cogvideox(prompt, steps=50, guidance=6.0):
    """
    ✅ ENDPOINT VÉRIFIÉ : zai-org/CogVideoX-2B-Space
    api_name="/generate"
    Retourne tuple (dict(video=filepath, subtitles=...), filepath_mp4, filepath_gif)
    """
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("zai-org/CogVideoX-2B-Space", verbose=False, **kw)
    result = c.predict(
        prompt=prompt,
        num_inference_steps=float(steps),
        guidance_scale=float(guidance),
        api_name="/generate"
    )
    # result[0] = dict(video=local_filepath, subtitles=...)
    path = extract_video_path(result)
    if path and Path(path).exists():
        return save_to_outputs(path, ".mp4")
    # Fallback : result[1] est direct filepath mp4
    if isinstance(result, (list, tuple)) and len(result) > 1:
        path2 = result[1]
        if path2 and Path(str(path2)).exists():
            return save_to_outputs(str(path2), ".mp4")
    raise RuntimeError("CogVideoX : aucun fichier vidéo récupéré")


async def gen_cogvideox(cid, prompt, steps=50):
    """✅ Branche principale — CogVideoX-2B via HF Space."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion CogVideoX Space…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    # Progression simulée pendant l'attente (Space = boîte noire)
    async def fake_progress():
        steps_ui = [
            (15, "Chargement CogVideoX-2B…"),
            (30, "Encodage du prompt…"),
            (55, "Génération des frames (GPU A10G)…"),
            (80, "Décodage vidéo…"),
            (92, "Assemblage MP4…"),
        ]
        for prog, label in steps_ui:
            if CLIPS.get(cid, {}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(20)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, _call_cogvideox, prompt, steps, 6.0)
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=f"CogVideoX: {e}")
    finally:
        tick.cancel()


def _call_animatediff(prompt, base="epiCRealism", motion="", step=4):
    """
    ByteDance/AnimateDiff-Lightning — /generate_image
    step doit être un int (pas une string).
    """
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("ByteDance/AnimateDiff-Lightning", verbose=False, **kw)
    # Essai 1 : paramètres nommés
    try:
        result = c.predict(
            prompt=prompt,
            base=base,
            motion=motion,
            step=int(step),
            api_name="/generate_image"
        )
    except TypeError:
        # Essai 2 : positionnels (certaines versions du Space changent les noms)
        result = c.predict(prompt, base, motion, int(step), api_name="/generate_image")
    path = extract_video_path(result)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    raise RuntimeError("AnimateDiff : aucun fichier vidéo récupéré")


async def gen_animatediff(cid, prompt, base="epiCRealism"):
    """✅ Branche rapide — AnimateDiff-Lightning (4 steps, ~30s)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion AnimateDiff-Lightning…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [(20,"Chargement modèle…"),(50,"Génération 4-step…"),(80,"Rendu GIF→MP4…")]:
            if CLIPS.get(cid,{}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(8)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, _call_animatediff, prompt, base, "", 4)
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=f"AnimateDiff: {e}")
    finally:
        tick.cancel()


async def gen_svd(cid, prompt, image_url=None):
    """✅ SVD — Stable Video Diffusion I2V via Pollinations image + SVD Space."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Génération image source Pollinations…", progress=10)
    tick = asyncio.create_task(tick_loop(cid, t))
    try:
        import urllib.parse
        # Step 1: generate source image via Pollinations if no image provided
        if not image_url:
            img_url = (f"https://image.pollinations.ai/prompt/"
                       f"{urllib.parse.quote(prompt)}?model=flux&width=1024&height=576&seed=369&nologo=true")
            async with aiohttp.ClientSession() as s:
                async with s.get(img_url, timeout=aiohttp.ClientTimeout(total=45)) as r:
                    if r.status != 200:
                        raise RuntimeError(f"Pollinations image HTTP {r.status}")
                    fname = f"{uuid.uuid4().hex[:12]}.jpg"
                    dest = OUTPUTS / fname
                    dest.write_bytes(await r.read())
                    src_img = str(dest)
        else:
            src_img = image_url
        upd(cid, progress=35, step="Connexion SVD Space…")
        loop = asyncio.get_event_loop()
        def _call_svd():
            c = Client("multimodalart/stable-video-diffusion", verbose=False)
            result = c.predict(
                image=handle_file(src_img),
                seed=369, randomize_seed=False,
                motion_bucket_id=127, fps_id=6,
                api_name="/video"
            )
            path = result[0] if isinstance(result, (list, tuple)) else result
            if path and Path(str(path)).exists():
                return save_to_outputs(str(path), ".mp4")
            raise RuntimeError("SVD: aucun fichier vidéo")
        upd(cid, progress=60, step="Génération SVD (image→vidéo)…")
        url = await loop.run_in_executor(None, _call_svd)
        upd(cid, progress=100, step="Vidéo SVD prête ✓", status="done", result=url)
    except Exception as e:
        upd(cid, status="error", error=f"SVD: {e}")
    finally:
        tick.cancel()


def _call_hf_space_generic(space_id, api_name, **kwargs):
    """Appel générique pour les Spaces qui nécessitent HF_TOKEN (Wan2.2, LTX)."""
    if not HF_TOKEN:
        raise RuntimeError(f"{space_id} nécessite HF_TOKEN dans .env")
    c = Client(space_id, hf_token=HF_TOKEN, verbose=False)
    result = c.predict(api_name=api_name, **kwargs)
    path = extract_video_path(result)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    raise RuntimeError(f"{space_id} : aucun fichier récupéré")


def _call_wan22(prompt, image_url=None):
    spaces = ["Wan-AI/Wan-2.2-5B", "fffiloni/Wan2.1"]
    for space_id in spaces:
        try:
            kw = {}
            if HF_TOKEN:
                kw["hf_token"] = HF_TOKEN
            c = Client(space_id, verbose=False, **kw)
            if image_url:
                result = c.predict(image=handle_file(image_url), prompt=prompt,
                                   num_frames=81, api_name="/generate_i2v")
            else:
                if space_id == "fffiloni/Wan2.1":
                    result = c.predict(txt2vid_prompt=prompt, resolution="720*1280",
                                       sd_steps=50, guide_scale=5.0, shift_scale=5.0,
                                       seed=-1, n_prompt="", api_name="/t2v_generation")
                else:
                    result = c.predict(prompt=prompt, num_frames=81, api_name="/generate_t2v")
            path = extract_video_path(result)
            if path and Path(str(path)).exists():
                return save_to_outputs(str(path), ".mp4")
        except Exception as e:
            log.warning(f"Wan22 {space_id} échoué: {e}, essai suivant…")
    raise RuntimeError("Wan2.2/Wan2.1: tous les Spaces ont échoué")


def _call_ltx(prompt, image_url=None):
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("Lightricks/ltx-video-distilled", verbose=False, **kw)
    if image_url:
        result = c.predict(
            prompt=prompt, negative_prompt="worst quality, inconsistent motion",
            image_filepath=handle_file(image_url), video_filepath=None,
            mode="image-to-video", height_ui=512, width_ui=704, duration_ui=3.0,
            ui_frames_to_use=9, seed_ui=369, randomize_seed=False,
            ui_guidance_scale=3.0, improve_texture_flag=True,
            api_name="/image_to_video"
        )
    else:
        result = c.predict(
            prompt=prompt, negative_prompt="worst quality, inconsistent motion",
            image_filepath=None, video_filepath=None,
            mode="text-to-video", height_ui=512, width_ui=704, duration_ui=3.0,
            ui_frames_to_use=9, seed_ui=369, randomize_seed=False,
            ui_guidance_scale=3.0, improve_texture_flag=True,
            api_name="/text_to_video"
        )
    path = extract_video_path(result)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    raise RuntimeError("LTX: aucun fichier vidéo récupéré")


async def gen_wan22(cid, prompt, image_url=None):
    """⚠  Wan2.2 — fallback vers fffiloni/Wan2.1 si Space principal KO."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion Wan2.2 Space…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [(15,"Chargement Wan2.2-TI2V-5B…"),(40,"Encodage…"),(70,"Génération 720P…"),(90,"Assemblage…")]:
            if CLIPS.get(cid,{}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(25)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, lambda: _call_wan22(prompt, image_url))
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo Wan2.2 prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


async def gen_ltx(cid, prompt, image_url=None):
    """⚠  LTX-Video — Space distilled (correct Space ID)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion LTX-Video Space…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [(20,"Chargement LTX 13B…"),(50,"DiT 30fps…"),(85,"Rendu HD…")]:
            if CLIPS.get(cid,{}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(20)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, lambda: _call_ltx(prompt, image_url))
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo LTX prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPATCHER + FALLBACK AUTOMATIQUE
# ═══════════════════════════════════════════════════════════════════════════════

async def run_clip(cid: str):
    clip   = CLIPS[cid]
    branch = clip["branch"]
    prompt = clip["prompt"]
    image  = clip.get("image")

    sem = SEMS.get(branch, SEMS["cogvideox"])
    async with sem:
        await _execute_branch(cid, branch, prompt, image)

        # FALLBACK AUTOMATIQUE si erreur
        if CLIPS[cid]["status"] == "error":
            fb = FALLBACK.get(branch)
            if fb:
                log.warning(f"Clip {cid} : fallback {branch} → {fb}")
                CLIPS[cid]["status"] = "running"
                CLIPS[cid]["error"]  = None
                upd(cid, branch=fb, step=f"Fallback vers {fb}…", progress=0)
                async with SEMS.get(fb, SEMS["cogvideox"]):
                    await _execute_branch(cid, fb, prompt, image)


async def _execute_branch(cid, branch, prompt, image):
    if branch == "pollinations-img":
        await gen_pollinations_image(cid, prompt)
    elif branch == "pollinations-vid":
        await gen_pollinations_video(cid, prompt)
    elif branch == "cogvideox":
        await gen_cogvideox(cid, prompt)
    elif branch == "animatediff":
        await gen_animatediff(cid, prompt)
    elif branch == "wan22":
        await gen_wan22(cid, prompt, image)
    elif branch == "ltx":
        await gen_ltx(cid, prompt, image)
    elif branch == "svd":
        await gen_svd(cid, prompt, image)
    else:
        await gen_cogvideox(cid, prompt)   # défaut sûr


def auto_branch(intent, index, total):
    if intent == "image":     return "pollinations-img"
    if intent == "draft":     return "pollinations-vid"
    if intent == "fast":      return "animatediff"
    if intent == "cinematic": return "cogvideox"
    if intent == "wan":       return "wan22"
    if intent == "hd30fps":   return "ltx"
    if intent == "t2v":       return "cogvideox"
    if intent == "i2v":       return "wan22"
    if intent == "svd":       return "svd"
    if intent == "mix":
        return ["cogvideox", "animatediff", "pollinations-vid"][index % 3]
    return "cogvideox"   # défaut le plus fiable confirmé


# ═══════════════════════════════════════════════════════════════════════════════
#  HANDLERS HTTP
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_options(request):
    return web.Response(headers=CORS, status=204)

async def handle_index(request):
    # Cherche le HTML dans plusieurs emplacements possibles
    candidates = [
        Path(__file__).parent / "tesla-go-v8.html",   # même dossier que proxy.py
        Path.cwd() / "tesla-go-v8.html",               # répertoire courant
        Path(__file__).parent.parent / "tesla-go-v8.html",  # dossier parent
    ]
    for p in candidates:
        if p.exists():
            return web.FileResponse(p)
    # Introuvable : message d'aide clair
    searched = "\n".join(str(c) for c in candidates)
    return web.Response(
        text=f"tesla-go-v8.html introuvable.\n\nEmplacements cherchés :\n{searched}\n\nPlace tesla-go-v8.html dans le même dossier que proxy.py.",
        status=404
    )

async def handle_health(request):
    return web.json_response({
        "status": "ok", "version": "V9-OPTIMIZED",
        "port": PORT, "gradio": HAS_GRADIO, "hf_token": bool(HF_TOKEN),
        "workers_active": sum(1 for c in CLIPS.values() if c["status"]=="running"),
        "clips_done": sum(1 for c in CLIPS.values() if c["status"]=="done"),
        "outputs_count": len(list(OUTPUTS.glob("*"))),
        "branches_confirmed": ["pollinations-img","pollinations-vid","cogvideox","animatediff"],
        "branches_need_token": ["wan22","ltx"],
        "sig": "Tik Tik Tik — Le UN ⚡"
    }, headers=CORS)

async def handle_capabilities(request):
    return web.json_response({
        "branches": [
            {"id":"pollinations-img","name":"Pollinations Images","ready":True,"token_required":False,"confirmed":True},
            {"id":"pollinations-vid","name":"Pollinations Vidéo","ready":True,"token_required":False,"confirmed":True,"note":"alpha"},
            {"id":"cogvideox","name":"CogVideoX-2B (HF Space)","ready":HAS_GRADIO,"token_required":False,"confirmed":True},
            {"id":"animatediff","name":"AnimateDiff-Lightning (HF Space)","ready":HAS_GRADIO,"token_required":False,"confirmed":True,"note":"rapide 4-step"},
            {"id":"wan22","name":"Wan2.2 TI2V-5B (HF Space)","ready":bool(HF_TOKEN),"token_required":True,"confirmed":False,"note":"Space parfois pausé"},
            {"id":"ltx","name":"LTX-Video 0.9.7 (HF Space)","ready":bool(HF_TOKEN),"token_required":True,"confirmed":False},
            {"id":"svd","name":"Stable Video Diffusion (I2V)","ready":HAS_GRADIO,"token_required":False,"confirmed":True,"note":"image→vidéo 4s"},
        ],
        "fallback_chains": FALLBACK,
        "parallel_mode": True,
    }, headers=CORS)

async def handle_produce(request):
    cleanup_old_clips()
    data      = await request.json()
    clips_def = data.get("clips", [])
    if not clips_def:
        return web.json_response({"error":"clips[] requis"}, status=400, headers=CORS)
    if len(clips_def) > 9:
        return web.json_response({"error":"max 9 clips"}, status=400, headers=CORS)

    sid = uuid.uuid4().hex[:8]
    clip_ids = []
    for i, c in enumerate(clips_def):
        prompt = c.get("prompt","").strip()
        if not prompt: continue
        intent = c.get("intent","t2v")
        branch = c.get("branch","auto")
        if branch == "auto": branch = auto_branch(intent, i, len(clips_def))
        cid = new_clip(sid, prompt, branch, intent, i)
        clip_ids.append(cid)

    SESSIONS[sid] = {"id":sid,"clip_ids":clip_ids,"status":"running","created":datetime.now().isoformat()}

    async def run_all():
        await asyncio.gather(*[run_clip(cid) for cid in clip_ids])
        SESSIONS[sid]["status"] = "done"

    asyncio.create_task(run_all())
    return web.json_response({"session_id":sid,"clip_ids":clip_ids,"total":len(clip_ids)}, headers=CORS)

async def handle_generate(request):
    """Compatibilité V7 — 1 clip."""
    data   = await request.json()
    prompt = data.get("prompt","").strip()
    if not prompt:
        return web.json_response({"error":"prompt requis"}, status=400, headers=CORS)
    intent = data.get("intent","t2v")
    branch = data.get("branch","auto")
    if branch == "auto": branch = auto_branch(intent, 0, 1)
    sid = uuid.uuid4().hex[:8]
    cid = new_clip(sid, prompt, branch, intent, 0)
    SESSIONS[sid] = {"id":sid,"clip_ids":[cid],"status":"running","created":datetime.now().isoformat()}
    asyncio.create_task(run_clip(cid))
    return web.json_response({"job_id":cid,"session_id":sid,"branch":branch}, headers=CORS)

async def handle_stream_session(request):
    """
    CORRECTION CRITIQUE [3] : SSE session avec ping keep-alive.
    Le frontend reconnecte automatiquement si la connexion coupe.
    """
    sid = request.match_info["session_id"]
    if sid not in SESSIONS:
        return web.Response(text="Session introuvable", status=404)

    resp = web.StreamResponse(headers={
        **CORS,
        "Content-Type":      "text/event-stream",
        "Cache-Control":     "no-cache",
        "X-Accel-Buffering": "no",
        "Connection":        "keep-alive",
    })
    await resp.prepare(request)

    def sse(d): return f"data: {json.dumps(d, ensure_ascii=False)}\n\n".encode()
    def ping(): return b": ping\n\n"   # keep-alive sans données

    clip_ids  = SESSIONS[sid]["clip_ids"]
    ping_tick = 0

    for _ in range(720):   # max 60 min
        clip_ids = SESSIONS[sid]["clip_ids"]
        clips_state = [CLIPS.get(cid,{}) for cid in clip_ids]

        try:
            await resp.write(sse({
                "session_id": sid,
                "clips": [{
                    "id":       c.get("id"),
                    "branch":   c.get("branch"),
                    "status":   c.get("status"),
                    "progress": c.get("progress",0),
                    "step":     c.get("step",""),
                    "elapsed":  c.get("elapsed",0),
                    "result":   c.get("result"),
                    "error":    c.get("error"),
                    "prompt":   c.get("prompt","")[:60],
                } for c in clips_state],
                "all_done": all(c.get("status") in ("done","error") for c in clips_state),
                "ts": time.time(),
            }))
        except Exception:
            break

        if all(c.get("status") in ("done","error") for c in clips_state):
            break

        await asyncio.sleep(2)
        ping_tick += 1
        if ping_tick % 15 == 0:   # ping toutes les 30s
            try: await resp.write(ping())
            except: break

    return resp

async def handle_stream_clip(request):
    cid = request.match_info["clip_id"]
    if cid not in CLIPS:
        return web.Response(text="Clip introuvable", status=404)
    resp = web.StreamResponse(headers={
        **CORS, "Content-Type":"text/event-stream",
        "Cache-Control":"no-cache", "X-Accel-Buffering":"no",
    })
    await resp.prepare(request)
    def sse(d): return f"data: {json.dumps(d)}\n\n".encode()
    for _ in range(720):
        c = CLIPS.get(cid,{})
        try:
            await resp.write(sse({
                "id":c.get("id"),"status":c.get("status"),
                "progress":c.get("progress",0),"step":c.get("step",""),
                "elapsed":c.get("elapsed",0),"result":c.get("result"),
                "error":c.get("error"),
            }))
        except: break
        if c.get("status") in ("done","error"): break
        await asyncio.sleep(2)
    return resp

async def handle_console(request):
    clips_out = [{
        "id":c["id"],"branch":c["branch"],
        "prompt":c["prompt"][:60],"status":c["status"],
        "progress":c["progress"],"step":c["step"],
        "elapsed":c["elapsed"],"result":c["result"],
    } for c in list(CLIPS.values())[-20:]]
    clips_out.sort(key=lambda x: {"running":0,"queued":1,"done":2,"error":3}.get(x["status"],9))
    return web.json_response({
        "clips":clips_out,"sessions":len(SESSIONS),
        "active":sum(1 for c in clips_out if c["status"]=="running"),
        "done":sum(1 for c in clips_out if c["status"]=="done"),
    }, headers=CORS)

async def handle_outputs(request):
    p = OUTPUTS / request.match_info["file"]
    return web.FileResponse(p, headers=CORS) if p.exists() else web.Response(
        text="Fichier introuvable", status=404)

async def handle_history(request):
    recent = sorted(SESSIONS.values(), key=lambda s:s["created"], reverse=True)[:10]
    return web.json_response([{
        "session_id":s["id"],"status":s["status"],"created":s["created"],
        "clips":[{"id":c.get("id"),"branch":c.get("branch"),
                  "status":c.get("status"),"result":c.get("result")}
                 for cid in s["clip_ids"] if (c:=CLIPS.get(cid))]
    } for s in recent], headers=CORS)


# ═══════════════════════════════════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════════════════════════════════

def create_app():
    app = web.Application()
    app.router.add_route("OPTIONS","/{path_info:.*}", handle_options)
    app.router.add_get("/",                               handle_index)
    app.router.add_get("/health",                         handle_health)
    app.router.add_get("/capabilities",                   handle_capabilities)
    app.router.add_post("/api/produce",                   handle_produce)
    app.router.add_post("/api/generate",                  handle_generate)
    app.router.add_get("/console",                        handle_console)
    app.router.add_get("/stream/session/{session_id}",    handle_stream_session)
    app.router.add_get("/stream/{clip_id}",               handle_stream_clip)
    app.router.add_get("/outputs/{file}",                 handle_outputs)
    app.router.add_get("/history",                        handle_history)
    return app

if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════╗
║  ⚡ TESLA GO V9 — CONSOLE DE PRODUCTION           ║
║  Endpoints vérifiés · Sauvegarde immédiate        ║
║  Fallback auto · SSE keep-alive                   ║
║  Port 8369 · LMDB17 / etheravolt.fr              ║
║  Tik Tik Tik — Le UN ⚡                          ║
╚═══════════════════════════════════════════════════╝
    """)
    if not HF_TOKEN:
        print("⚠  HF_TOKEN absent → CogVideoX et AnimateDiff fonctionnent quand même")
        print("   Wan2.2 et LTX-Video nécessitent un token → hf.co/settings/tokens\n")
    web.run_app(create_app(), host=HOST, port=PORT)
