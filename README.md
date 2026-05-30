# ⚡ TESLA GO V8 — Console de Production Parallèle

> **LMDB17 / etheravolt.fr** · Tik Tik Tik — Le UN ⚡

Génération vidéo IA **parallèle** 100% gratuite — plusieurs clips simultanément
via les data centers HuggingFace Spaces (GPU A10G) + Pollinations.

---

## 🚀 Démarrage (Windows)

```bash
# 1. Cloner
git clone https://github.com/lemarchanddebonheur9/tesla-go.git
cd tesla-go

# 2. Token HF gratuit → hf.co/settings/tokens
copy .env.example .env
# éditer .env → HF_TOKEN=hf_xxxxx

# 3. Lancer
start.bat       # ou : python proxy.py
```

→ Navigateur s'ouvre sur `http://127.0.0.1:8369`

---

## ⚡ Architecture parallèle

```
Frontend (tesla-go-v8.html)
         │
         │  POST /api/produce  [{clips: [...]}]
         ▼
  proxy.py (aiohttp :8369)
         │
         │  asyncio.gather() ← PARALLÈLE
         │
   ┌─────┼─────┬─────┐
   ▼     ▼     ▼     ▼
Worker  Worker Worker Worker
Wan2.2  CogVX   LTX  Polli
HF GPU  HF GPU HF GPU Cloud
   │     │     │     │
   └─────┴─────┴─────┘
         │
    SSE /stream/session/{id}
         │
    Frontend → barres temps réel
```

Chaque Worker tourne sur le **GPU A10G** de HuggingFace (gratuit).
Résultat : 4 clips générés en parallèle ≈ temps d'1 seul clip séquentiel.

---

## 🌊 Branches disponibles

| Branche | Modèle | GPU Cloud | Coût |
|---------|--------|-----------|------|
| `wan22` | Wan2.2 TI2V-5B | HF A10G | **0 €** |
| `cogvideox` | CogVideoX-2B | HF A10G | **0 €** |
| `ltx` | LTX-Video 0.9.7 | HF A10G | **0 €** |
| `pollinations-img` | Flux.1 | Cloud Pollinations | **0 €** |
| `pollinations-vid` | Seedance | Cloud Pollinations | **0 €** |
| `local` | Wan2.2 TI2V-5B | Ton GPU (24Go+) | **0 €** |

Mode `mix` → distribue automatiquement sur wan22 / cogvideox / ltx en round-robin.

---

## 📡 API Routes

| Méthode | Route | Description |
|---------|-------|-------------|
| POST | `/api/produce` | Lancer N clips en parallèle |
| POST | `/api/generate` | Compatibilité V7 (1 clip) |
| GET | `/console` | État JSON de tous les workers |
| GET | `/stream/{clip_id}` | SSE par clip |
| GET | `/stream/session/{id}` | SSE session complète |
| GET | `/health` | Statut proxy |
| GET | `/capabilities` | Branches disponibles |
| GET | `/history` | Sessions récentes |

---

## 🔑 Sources GitHub (tous Apache 2.0)

- [pollinations/pollinations](https://github.com/pollinations/pollinations)
- [Wan-Video/Wan2.2](https://github.com/Wan-Video/Wan2.2)
- [zai-org/CogVideo](https://github.com/zai-org/CogVideo)
- [Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video)

---

*LMDB17 · etheravolt.fr · « À LA DÉCOUVERTE DE L'INVISIBLE »*
