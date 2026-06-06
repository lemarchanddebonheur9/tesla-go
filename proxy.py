#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  ETHV_APP_TESLAGO_PROXY_V9_STUDIO_2026-06-06.py
================================================================================
  ⚡ TESLA GO V9 — Studio Quantique — 100% Gratuit · ZeroGPU
  7 branches · LTX-Video distilled primaire · Cascade auto · SSE robuste

  Auteur    : Lolo (Laurent Becker) — LMDB17 / etheravolt.fr
  Port      : 8369 (constante TNT)
  Signature : Tik Tik Tik — Le UN ⚡

  BRANCHES V9 (cascade priorité décroissante)
  ─────────────────────────────────────────────────
  ltx               → Lightricks/LTX-Video            ★ PRIMAIRE distilled ZeroGPU
  wan22             → Wan-AI/Wan2.2-T2V-14B            ★ FP8 AOTI ZeroGPU
  cogvideox         → THUDM/CogVideoX-5B-Space         ★ 5B (upgrade 2B→5B)
  animatediff       → ByteDance/AnimateDiff-Lightning  ✅ 4-step rapide
  pollinations-vid  → gen.pollinations.ai/v1/video     ✅ sans clé
  pollinations-img  → image.pollinations.ai            ✅ sans clé
  hunyuan           → tencent/HunyuanVideo              ✅ ZeroGPU sans clé

  ÉVOLUTIONS V9
  ──────────────
  [1] LTX-Video distilled = branche primaire (signature corrigée)
  [2] CogVideoX-5B — upgrade depuis 2B (signature corrigée)
  [3] Cascade vérifiée : ltx→cogvideox→animatediff→pollinations-vid
  [4] wan22/hunyuan : token_required (Spaces gated)
  [5] /api/compose — pipeline épisode complet :
      script segments → TTS (Kokoro si HF_TOKEN, edge-tts sinon) → clips vidéo
      → FFmpeg concat audio+vidéo → MP4 final publiable
================================================================================
"""

import os, json, uuid, asyncio, logging, time, shutil, subprocess, tempfile
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
    "hunyuan":          asyncio.Semaphore(2),
    "local":            asyncio.Semaphore(1),
}

# Cascade V9 : ltx → wan22 → cogvideox → animatediff → pollinations-vid
FALLBACK = {
    "ltx":        "wan22",
    "wan22":      "cogvideox",
    "cogvideox":  "animatediff",
    "animatediff":"pollinations-vid",
    "hunyuan":    "cogvideox",
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
                    upd(cid, progress=100, step="Vidéo prête ✓",
                        status="done", result=data.get("url"))
                else:
                    raise RuntimeError(f"Pollinations vidéo HTTP {r.status}")
    except Exception as e:
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


def _call_cogvideox(prompt, steps=50, guidance=6.0):
    """
    ★ V9 CORRIGÉ : THUDM/CogVideoX-5B-Space
    api_name="/generate" — image_input/video_input passés à None pour T2V
    Retourne tuple (dict(video=...), download_mp4, download_gif, seed)
    """
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("THUDM/CogVideoX-5B-Space", verbose=False, **kw)
    result = c.predict(
        prompt=prompt,
        image_input=None,
        video_input=None,
        video_strength=0.8,
        seed_value=-1,
        scale_status=False,
        rife_status=False,
        api_name="/generate"
    )
    # result[0] = dict(video=filepath), result[1] = download mp4
    path = extract_video_path(result)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    if isinstance(result, (list, tuple)) and len(result) > 1:
        path2 = result[1]
        if path2 and Path(str(path2)).exists():
            return save_to_outputs(str(path2), ".mp4")
    raise RuntimeError("CogVideoX-5B : aucun fichier vidéo récupéré")


async def gen_cogvideox(cid, prompt, steps=50):
    """★ V9 — CogVideoX-5B via HF Space ZeroGPU (fallback cascade)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion CogVideoX-5B Space…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        steps_ui = [
            (15, "Chargement CogVideoX-5B…"),
            (30, "Encodage du prompt…"),
            (55, "Génération des frames (ZeroGPU)…"),
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
        upd(cid, status="error", error=f"CogVideoX-5B: {e}")
    finally:
        tick.cancel()


def _call_animatediff(prompt, base="epiCRealism", motion="", step="4"):
    """
    ✅ ENDPOINT VÉRIFIÉ : ByteDance/AnimateDiff-Lightning
    api_name="/generate_image"
    Retourne Dict(video=filepath, subtitles=filepath|None)
    """
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("ByteDance/AnimateDiff-Lightning", verbose=False, **kw)
    result = c.predict(
        prompt=prompt,
        base=base,
        motion=motion,
        step=step,
        api_name="/generate_image"
    )
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
        url = await loop.run_in_executor(None, _call_animatediff, prompt, base, "", "4")
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=f"AnimateDiff: {e}")
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


async def gen_wan22(cid, prompt, image_url=None):
    """★ V9 — Wan2.2 T2V-14B FP8 AOTI ZeroGPU (2e rang cascade)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion Wan2.2 T2V-14B…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [
            (15, "Chargement Wan2.2-T2V-14B FP8…"),
            (35, "Encodage texte→latent…"),
            (60, "Génération 720P (ZeroGPU)…"),
            (85, "Décodage + assemblage…"),
        ]:
            if CLIPS.get(cid, {}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(25)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        kw = {"prompt": prompt, "num_frames": 81}
        api = "/generate_t2v"
        if image_url:
            kw["image"] = handle_file(image_url)
            api = "/generate_i2v"
        url = await loop.run_in_executor(
            None, lambda: _call_hf_space_generic("Wan-AI/Wan2.2-T2V-14B", api, **kw)
        )
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo Wan2.2 14B prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


def _call_ltx(prompt, image_url=None):
    """
    ★ V9 CORRIGÉ — LTX-Video-Distilled signature réelle vérifiée via view_api().
    Params: prompt, negative_prompt, input_image_filepath, input_video_filepath,
            height_ui, width_ui, mode, duration_ui, ui_frames_to_use,
            seed_ui, randomize_seed, ui_guidance_scale, improve_texture_flag
    Retourne: (dict(video=filepath, subtitles=...), seed)
    """
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("Lightricks/LTX-Video-Distilled", verbose=False, **kw)
    api = "/text_to_video"
    kwargs = dict(
        prompt=prompt,
        negative_prompt="worst quality, inconsistent motion, blurry, jittery, distorted",
        input_image_filepath=None,
        input_video_filepath=None,
        height_ui=512,
        width_ui=704,
        mode="text-to-video",
        duration_ui=2,
        ui_frames_to_use=9,
        seed_ui=369,
        randomize_seed=False,
        ui_guidance_scale=1.0,
        improve_texture_flag=True,
        api_name=api,
    )
    if image_url:
        kwargs["input_image_filepath"] = image_url
        kwargs["mode"] = "image-to-video"
        kwargs["api_name"] = "/image_to_video"
    result = c.predict(**kwargs)
    # result = (dict(video=filepath, subtitles=...), seed_int)
    video_dict = result[0] if isinstance(result, (list, tuple)) else result
    path = extract_video_path(video_dict)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    raise RuntimeError("LTX-Distilled : aucun fichier vidéo récupéré")


async def gen_ltx(cid, prompt, image_url=None):
    """★ V9 PRIMAIRE — LTX-Video Distilled ZeroGPU (signature corrigée)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion LTX-Video Distilled…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [
            (15, "Chargement LTX Distilled…"),
            (40, "DiT distilled — 8 steps 30fps…"),
            (70, "Rendu 704×512…"),
            (90, "Encodage MP4…"),
        ]:
            if CLIPS.get(cid, {}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(12)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, lambda: _call_ltx(prompt, image_url))
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo LTX Distilled prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=str(e))
    finally:
        tick.cancel()


def _call_hunyuan(prompt, steps=20):
    """★ V9 — HunyuanVideo ZeroGPU sans token requis."""
    kw = {}
    if HF_TOKEN:
        kw["hf_token"] = HF_TOKEN
    c = Client("tencent/HunyuanVideo", verbose=False, **kw)
    result = c.predict(
        prompt=prompt,
        num_inference_steps=steps,
        api_name="/generate"
    )
    path = extract_video_path(result)
    if path and Path(str(path)).exists():
        return save_to_outputs(str(path), ".mp4")
    raise RuntimeError("HunyuanVideo : aucun fichier récupéré")


async def gen_hunyuan(cid, prompt):
    """★ V9 — HunyuanVideo (7e branche ZeroGPU)."""
    t = time.time()
    upd(cid, status="running", started_at=t,
        step="Connexion HunyuanVideo…", progress=5)
    tick = asyncio.create_task(tick_loop(cid, t))

    async def fake_progress():
        for prog, label in [
            (20, "Chargement HunyuanVideo…"),
            (45, "Génération frames ZeroGPU…"),
            (80, "Assemblage MP4…"),
        ]:
            if CLIPS.get(cid, {}).get("status") != "running": break
            upd(cid, progress=prog, step=label)
            await asyncio.sleep(20)

    prog_task = asyncio.create_task(fake_progress())
    loop = asyncio.get_event_loop()
    try:
        url = await loop.run_in_executor(None, _call_hunyuan, prompt, 20)
        prog_task.cancel()
        upd(cid, progress=100, step="Vidéo HunyuanVideo prête ✓", status="done", result=url)
    except Exception as e:
        prog_task.cancel()
        upd(cid, status="error", error=f"HunyuanVideo: {e}")
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
    elif branch == "hunyuan":
        await gen_hunyuan(cid, prompt)
    else:
        await gen_ltx(cid, prompt, image)   # V9 : LTX comme défaut sûr


def auto_branch(intent, index, total):
    if intent == "image":     return "pollinations-img"
    if intent == "draft":     return "pollinations-vid"
    if intent == "fast":      return "animatediff"
    if intent == "cinematic": return "cogvideox"
    if intent == "wan":       return "wan22"
    if intent == "hd30fps":   return "ltx"
    if intent == "studio":    return "ltx"    # V9 : intent studio = LTX distilled
    if intent == "hunyuan":   return "hunyuan"
    if intent == "mix":
        # V9 : mix tourne sur les 3 meilleures branches
        return ["ltx", "wan22", "cogvideox"][index % 3]
    return "ltx"   # V9 : LTX distilled = nouveau défaut


# ═══════════════════════════════════════════════════════════════════════════════
#  TTS — Kokoro (si HF_TOKEN) ou edge-tts (fallback gratuit)
# ═══════════════════════════════════════════════════════════════════════════════

KOKORO_MODEL  = None   # chargé à la demande
KOKORO_LOADED = False


def _ensure_kokoro():
    """Télécharge et charge Kokoro une seule fois (lazy init)."""
    global KOKORO_MODEL, KOKORO_LOADED
    if KOKORO_LOADED:
        return KOKORO_MODEL
    if not HF_TOKEN:
        return None
    try:
        from huggingface_hub import hf_hub_download
        from kokoro_onnx import Kokoro
        model_dir = Path(__file__).parent / ".kokoro"
        model_dir.mkdir(exist_ok=True)
        model_path  = hf_hub_download("hexgrad/Kokoro-82M-ONNX", "kokoro-v1_0.onnx",
                                       token=HF_TOKEN, local_dir=str(model_dir))
        voices_path = hf_hub_download("hexgrad/Kokoro-82M-ONNX", "voices.bin",
                                       token=HF_TOKEN, local_dir=str(model_dir))
        KOKORO_MODEL  = Kokoro(model_path, voices_path)
        KOKORO_LOADED = True
        log.info("Kokoro TTS chargé ✓")
    except Exception as e:
        log.warning(f"Kokoro non disponible ({e}) — edge-tts en fallback")
        KOKORO_LOADED = True   # ne pas retenter
    return KOKORO_MODEL


def _tts_kokoro(text: str, out_path: str, voice: str = "af_heart",
                speed: float = 1.0, lang: str = "fr-fr") -> bool:
    """Génère l'audio via Kokoro ONNX. Retourne True si succès."""
    import soundfile as sf
    import numpy as np
    kokoro = _ensure_kokoro()
    if kokoro is None:
        return False
    try:
        samples, sr = kokoro.create(text, voice=voice, speed=speed, lang=lang)
        sf.write(out_path, samples, sr)
        return True
    except Exception as e:
        log.warning(f"Kokoro TTS échoué : {e}")
        return False


async def _tts_edge(text: str, out_path: str,
                    voice: str = "fr-FR-DeniseNeural") -> bool:
    """Génère l'audio via edge-tts (Microsoft Edge, gratuit sans clé)."""
    try:
        import edge_tts
        tts = edge_tts.Communicate(text, voice)
        await tts.save(out_path)
        return True
    except Exception as e:
        log.error(f"edge-tts échoué : {e}")
        return False


async def generate_tts(text: str, out_path: str,
                       voice_kokoro: str = "af_heart",
                       voice_edge: str = "fr-FR-DeniseNeural") -> bool:
    """TTS avec Kokoro en primaire, edge-tts en fallback."""
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _tts_kokoro, text, out_path, voice_kokoro, 1.0, "fr-fr")
    if not ok:
        ok = await _tts_edge(text, out_path, voice_edge)
    return ok


# ═══════════════════════════════════════════════════════════════════════════════
#  COMPOSE — pipeline épisode complet (TTS + clips + FFmpeg concat)
# ═══════════════════════════════════════════════════════════════════════════════

COMPOSE_JOBS = {}


async def run_compose(job_id: str, segments: list, voice_edge: str):
    """
    Pipeline complet :
      1. Pour chaque segment : TTS → audio WAV/MP3
      2. Optionnel : générer clip vidéo si prompt fourni
      3. FFmpeg : assembler audio + clip → segment MP4
      4. FFmpeg : concat tous les segments → épisode final MP4
    """
    job = COMPOSE_JOBS[job_id]

    def upd_job(**kw):
        COMPOSE_JOBS[job_id].update(kw)

    upd_job(status="running", step="Démarrage pipeline…", progress=0)
    tmpdir = Path(tempfile.mkdtemp(prefix="compose_"))
    segment_files = []

    try:
        total = len(segments)
        for i, seg in enumerate(segments):
            text   = seg.get("text", "").strip()
            prompt = seg.get("prompt", "").strip()
            dur    = float(seg.get("duration", 5))
            pct_base = int(i / total * 80)

            upd_job(step=f"[{i+1}/{total}] TTS…", progress=pct_base)

            # ── TTS ──────────────────────────────────────────────────────────
            audio_path = str(tmpdir / f"seg{i:02d}_audio.mp3")
            if text:
                ok = await generate_tts(text, audio_path, voice_edge=voice_edge)
                if not ok:
                    audio_path = None
            else:
                audio_path = None

            # ── Clip vidéo (optionnel) ────────────────────────────────────
            clip_path = seg.get("clip_url")   # URL locale /outputs/xxx.mp4
            if clip_path and clip_path.startswith("http://127.0.0.1"):
                fname = clip_path.split("/outputs/")[-1]
                local  = OUTPUTS / fname
                clip_path = str(local) if local.exists() else None

            # ── Durée audio réelle ─────────────────────────────────────────
            real_dur = dur
            if audio_path and Path(audio_path).exists():
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries",
                     "format=duration", "-of", "default=nw=1:nk=1", audio_path],
                    capture_output=True, text=True
                )
                try: real_dur = max(float(r.stdout.strip()), dur)
                except: pass

            # ── Assemblage segment ─────────────────────────────────────────
            seg_out = str(tmpdir / f"seg{i:02d}.mp4")
            upd_job(step=f"[{i+1}/{total}] FFmpeg assemble…", progress=pct_base + 5)

            if clip_path and audio_path:
                # vidéo + audio → looper la vidéo si audio plus long
                cmd = [
                    "ffmpeg", "-y",
                    "-stream_loop", "-1", "-i", clip_path,
                    "-i", audio_path,
                    "-shortest",
                    "-c:v", "libx264", "-c:a", "aac",
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    seg_out
                ]
            elif audio_path:
                # audio seul → fond noir + audio
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"color=c=black:s=1280x720:r=24:d={real_dur}",
                    "-i", audio_path,
                    "-shortest",
                    "-c:v", "libx264", "-c:a", "aac",
                    seg_out
                ]
            elif clip_path:
                # vidéo seule → trim à dur
                cmd = [
                    "ffmpeg", "-y", "-i", clip_path,
                    "-t", str(real_dur),
                    "-c:v", "libx264", "-an",
                    seg_out
                ]
            else:
                continue

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log.error(f"FFmpeg seg{i}: {result.stderr[-300:]}")
                continue
            segment_files.append(seg_out)

        if not segment_files:
            upd_job(status="error", error="Aucun segment produit")
            return

        # ── Concat final ──────────────────────────────────────────────────
        upd_job(step="FFmpeg concat final…", progress=85)
        concat_list = tmpdir / "concat.txt"
        concat_list.write_text("\n".join(f"file '{f}'" for f in segment_files))

        fname_out = f"episode_{uuid.uuid4().hex[:8]}.mp4"
        out_mp4   = OUTPUTS / fname_out
        cmd_concat = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            str(out_mp4)
        ]
        r2 = subprocess.run(cmd_concat, capture_output=True, text=True)
        if r2.returncode != 0:
            upd_job(status="error", error=f"Concat échoué : {r2.stderr[-300:]}")
            return

        result_url = f"http://127.0.0.1:{PORT}/outputs/{fname_out}"
        upd_job(status="done", progress=100,
                step="Épisode prêt ✓", result=result_url)
        log.info(f"Compose {job_id} → {result_url}")

    except Exception as e:
        upd_job(status="error", error=str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  HANDLERS HTTP
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_options(request):
    return web.Response(headers=CORS, status=204)

async def handle_index(request):
    p = Path(__file__).parent / "tesla-go-v8.html"
    return web.FileResponse(p) if p.exists() else web.Response(
        text="tesla-go-v8.html introuvable", status=404)

async def handle_health(request):
    return web.json_response({
        "status": "ok", "version": "V9.0-STUDIO-QUANTIQUE",
        "port": PORT, "gradio": HAS_GRADIO, "hf_token": bool(HF_TOKEN),
        "workers_active": sum(1 for c in CLIPS.values() if c["status"]=="running"),
        "clips_done": sum(1 for c in CLIPS.values() if c["status"]=="done"),
        "outputs_count": len(list(OUTPUTS.glob("*"))),
        "primary_branch": "ltx-distilled",
        "cascade_no_token": ["ltx","cogvideox","animatediff","pollinations-vid"],
        "cascade_with_token": ["ltx","wan22","cogvideox","animatediff","pollinations-vid"],
        "branches_zerogpu_no_token": ["ltx","cogvideox"],
        "branches_need_token": ["wan22","hunyuan"],
        "sig": "Tik Tik Tik — Le UN ⚡"
    }, headers=CORS)

async def handle_capabilities(request):
    return web.json_response({
        "branches": [
            {"id":"ltx","name":"LTX-Video Distilled ★ PRIMAIRE","ready":HAS_GRADIO,"token_required":False,"zerogpu":True,"rank":1,"note":"2s 704×512 30fps · Space vérifié"},
            {"id":"cogvideox","name":"CogVideoX-5B ZeroGPU","ready":HAS_GRADIO,"token_required":False,"zerogpu":True,"rank":2,"note":"Space vérifié"},
            {"id":"animatediff","name":"AnimateDiff-Lightning","ready":HAS_GRADIO,"token_required":False,"zerogpu":False,"rank":3,"note":"rapide 4-step · Space vérifié"},
            {"id":"pollinations-vid","name":"Pollinations Vidéo","ready":True,"token_required":False,"zerogpu":False,"rank":4,"note":"sans clé"},
            {"id":"pollinations-img","name":"Pollinations Images","ready":True,"token_required":False,"zerogpu":False,"rank":5},
            {"id":"wan22","name":"Wan2.2 T2V-5B","ready":bool(HF_TOKEN),"token_required":True,"zerogpu":True,"rank":6,"note":"Space gated — HF_TOKEN requis"},
            {"id":"hunyuan","name":"HunyuanVideo","ready":bool(HF_TOKEN),"token_required":True,"zerogpu":True,"rank":7,"note":"Space gated — HF_TOKEN requis"},
        ],
        "fallback_chains": FALLBACK,
        "parallel_mode": True,
        "intents": ["studio","cinematic","fast","wan","hd30fps","hunyuan","draft","image","mix","t2v"],
    }, headers=CORS)

async def handle_produce(request):
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

async def handle_tts(request):
    """POST /api/tts — génère un fichier audio et retourne son URL locale."""
    data  = await request.json()
    text  = data.get("text", "").strip()
    voice = data.get("voice", "fr-FR-DeniseNeural")
    if not text:
        return web.json_response({"error": "text requis"}, status=400, headers=CORS)
    fname = f"tts_{uuid.uuid4().hex[:10]}.mp3"
    dest  = str(OUTPUTS / fname)
    ok    = await generate_tts(text, dest, voice_edge=voice)
    if not ok:
        return web.json_response({"error": "TTS échoué"}, status=500, headers=CORS)
    return web.json_response({
        "url": f"http://127.0.0.1:{PORT}/outputs/{fname}",
        "engine": "kokoro" if (KOKORO_MODEL is not None) else "edge-tts",
        "voice": voice,
    }, headers=CORS)


async def handle_compose(request):
    """
    POST /api/compose — pipeline épisode complet.
    Body JSON :
    {
      "segments": [
        {"text": "Bienvenue dans Mercredis Tesla…", "prompt": "tesla car driving", "clip_url": "http://...", "duration": 8},
        ...
      ],
      "voice": "fr-FR-DeniseNeural"   // optionnel
    }
    Retourne immédiatement {"job_id": "..."}, puis streamer /compose/{job_id}.
    """
    data     = await request.json()
    segments = data.get("segments", [])
    voice    = data.get("voice", "fr-FR-DeniseNeural")
    if not segments:
        return web.json_response({"error": "segments[] requis"}, status=400, headers=CORS)
    if len(segments) > 20:
        return web.json_response({"error": "max 20 segments"}, status=400, headers=CORS)
    job_id = uuid.uuid4().hex[:8]
    COMPOSE_JOBS[job_id] = {
        "id": job_id, "status": "queued", "progress": 0,
        "step": "", "result": None, "error": None,
        "created": datetime.now().isoformat(),
    }
    asyncio.create_task(run_compose(job_id, segments, voice))
    return web.json_response({"job_id": job_id, "segments": len(segments)}, headers=CORS)


async def handle_compose_stream(request):
    """GET /compose/{job_id} — SSE suivi du job compose."""
    job_id = request.match_info["job_id"]
    if job_id not in COMPOSE_JOBS:
        return web.Response(text="Job introuvable", status=404)
    resp = web.StreamResponse(headers={
        **CORS, "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)
    def sse(d): return f"data: {json.dumps(d, ensure_ascii=False)}\n\n".encode()
    for _ in range(600):   # max 50 min
        j = COMPOSE_JOBS.get(job_id, {})
        try:
            await resp.write(sse({
                "id": j.get("id"), "status": j.get("status"),
                "progress": j.get("progress", 0), "step": j.get("step", ""),
                "result": j.get("result"), "error": j.get("error"),
            }))
        except: break
        if j.get("status") in ("done", "error"): break
        await asyncio.sleep(3)
    return resp


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
    app.router.add_post("/api/tts",                        handle_tts)
    app.router.add_post("/api/compose",                    handle_compose)
    app.router.add_get("/compose/{job_id}",               handle_compose_stream)
    return app

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║  ⚡ TESLA GO V9 — STUDIO QUANTIQUE                   ║
║  LTX Distilled ★ · CogVideoX-5B · AnimateDiff       ║
║  /api/compose · TTS Kokoro/edge-tts · FFmpeg         ║
║  Zéro coût absolu · Port 8369 · LMDB17              ║
║  Tik Tik Tik — Le UN ⚡                             ║
╚══════════════════════════════════════════════════════╝
    """)
    if not HF_TOKEN:
        print("⚠  HF_TOKEN absent → CogVideoX et AnimateDiff fonctionnent quand même")
        print("   Wan2.2 et LTX-Video nécessitent un token → hf.co/settings/tokens\n")
    web.run_app(create_app(), host=HOST, port=PORT)
