"""
ChronoBirth – backend leggero
=============================
Endpoint:
  POST /api/natal          → tema natale + cielo + transiti
  GET  /api/name-meaning   → dizionario da JSON + NameAPI opzionale + traduzione
  GET  /api/health         → stato servizio
  GET  /                   → info API

I significati dei nomi NON sono hard-coded qui: vengono letti da
  - ../name_meanings.json  (root progetto, allineato al frontend)
  - oppure data/name_meanings.json (copia per deploy backend-only)
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ephemeris import NatalInput, compute_natal, engine_info

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
STATIC_DIR = ROOT

app = FastAPI(
    title="ChronoBirth API",
    description="Backend ChronoBirth (tema natale, name meaning da JSON, traduzione open source).",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dizionario nomi da file JSON (non inline)
# ---------------------------------------------------------------------------
def _name_json_candidates() -> list[Path]:
    env = os.getenv("NAME_MEANINGS_PATH", "").strip()
    paths: list[Path] = []
    if env:
        paths.append(Path(env))
    paths.extend(
        [
            ROOT / "name_meanings.json",
            BACKEND_DIR / "data" / "name_meanings.json",
            BACKEND_DIR / "name_meanings.json",
        ]
    )
    return paths


@lru_cache(maxsize=1)
def load_name_meanings() -> dict[str, str]:
    for path in _name_json_candidates():
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    print(f"[names] caricati {len(data)} significati da {path}")
                    return {
                        str(k).lower().strip(): str(v)
                        for k, v in data.items()
                        if k and v
                    }
        except Exception as exc:  # noqa: BLE001
            print(f"[names] errore lettura {path}: {exc}")
    print("[names] name_meanings.json non trovato – dizionario vuoto")
    return {}


def name_dict_info() -> dict[str, Any]:
    d = load_name_meanings()
    used = next((str(p) for p in _name_json_candidates() if p.is_file()), None)
    return {"count": len(d), "path": used}


# ---------------------------------------------------------------------------
# Modelli
# ---------------------------------------------------------------------------
class NatalRequest(BaseModel):
    name: str = Field(default="Anonimo", max_length=120)
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM o HH:MM:SS")
    place: str = Field(default="", max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    timezone: str = Field(..., description="IANA, es. Europe/Rome")
    house_system: str = Field(default="P", max_length=1)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            raise ValueError("date deve essere YYYY-MM-DD")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not v:
            raise ValueError("time obbligatoria")
        if len(v.split(":")) not in (2, 3):
            raise ValueError("time deve essere HH:MM o HH:MM:SS")
        return v

    @field_validator("house_system")
    @classmethod
    def validate_hs(cls, v: str) -> str:
        return (v or "P").upper()[:1]


# ---------------------------------------------------------------------------
# Traduzione open source
# ---------------------------------------------------------------------------
def _looks_english(text: str) -> bool:
    t = f" {text.lower()} "
    if any(ch in text.lower() for ch in "àèéìòù"):
        return False
    en = (
        " the ", " of ", " and ", " from ", " gift ", " beloved ", " light ",
        " warrior ", " grace ", " noble ", " hebrew ", " latin ", " greek ", " meaning ",
    )
    return any(x in t for x in en) or bool(
        re.search(r"\b(the|and|of|gift|beloved|light|warrior|grace|noble)\b", text, re.I)
    )


async def _translate_en_it(text: str) -> tuple[str, str]:
    if not text or not _looks_english(text):
        return text, "skip"

    bases: list[str] = []
    env = os.getenv("LIBRETRANSLATE_URL", "").strip().rstrip("/")
    if env:
        bases.append(env)
    bases.extend(
        [
            "https://libretranslate.com",
            "https://translate.argosopentech.com",
            "https://trans.zillyhuhn.com",
        ]
    )
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=8.0) as client:
        for base in bases:
            if not base or base in seen:
                continue
            seen.add(base)
            try:
                resp = await client.post(
                    f"{base}/translate",
                    json={"q": text, "source": "en", "target": "it", "format": "text"},
                    headers={"Content-Type": "application/json"},
                )
                if resp.is_success:
                    data = resp.json()
                    out = data.get("translatedText") or data.get("translation")
                    if out and str(out).strip():
                        return str(out).strip(), f"libretranslate:{base}"
            except Exception:
                continue
        try:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": "en|it"},
            )
            if resp.is_success:
                data = resp.json()
                out = (data.get("responseData") or {}).get("translatedText")
                if out and not re.search(r"QUERY LENGTH|INVALID|ERROR", str(out), re.I):
                    return str(out).strip(), "mymemory"
        except Exception:
            pass
    return text, "none"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    info = engine_info()
    names = name_dict_info()
    return {
        "ok": True,
        "service": "chronobirth-backend",
        "version": "1.1.0",
        "engine": info["engine"],
        "engine_version": info["engine_version"],
        "has_swiss": info["has_swiss"],
        "names_count": names["count"],
        "names_path": names["path"],
        "port": os.getenv("PORT"),
        "note": (
            "Swiss Ephemeris attivo"
            if info["has_swiss"]
            else "Motore pure-Python (pyswisseph non installato). Su Windows/Render Free è normale senza C++ Build Tools."
        ),
    }


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "ChronoBirth API",
        "docs": "/docs",
        "health": "/api/health",
        "natal": "POST /api/natal",
        "name_meaning": "GET /api/name-meaning?name=...",
        "app": "/index.html",
    }


@app.post("/api/natal")
def api_natal(body: NatalRequest) -> dict[str, Any]:
    try:
        return compute_natal(
            NatalInput(
                name=body.name.strip() or "Anonimo",
                date=body.date,
                time=body.time,
                place=body.place or "",
                lat=body.lat,
                lon=body.lon,
                timezone=body.timezone,
                house_system=body.house_system,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Errore calcolo ephemeris: {e}") from e


@app.get("/api/name-meaning")
async def api_name_meaning(
    name: str = Query(..., min_length=1, max_length=80),
    apiKey: Optional[str] = Query(default=None, alias="apiKey"),
    translate: str = Query(default="1", description="1=traduci EN→IT se serve"),
) -> dict[str, Any]:
    """
    1) dizionario da name_meanings.json
    2) se apiKey + NAMEAPI_URL → NameAPI
    3) traduzione open source EN→IT opzionale
    """
    key = name.strip().lower()
    first = key.split()[0] if key else ""
    do_translate = translate not in ("0", "false", "False", "no")
    dictionary = load_name_meanings()

    if first in dictionary:
        return {
            "name": name,
            "meaning": dictionary[first],
            "source": "local-json",
            "translated": False,
            "translator": None,
        }

    meaning: Optional[str] = None
    source = "none"

    if apiKey:
        url = os.getenv("NAMEAPI_URL", "").strip()
        if url:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(url, params={"name": name, "apiKey": apiKey})
                    if resp.is_success:
                        data = resp.json()
                        raw = data.get("meaning") or data.get("result") or data.get("description")
                        if raw:
                            meaning = str(raw)
                            source = "nameapi"
            except Exception:
                pass

    translated = False
    translator = None
    if meaning and do_translate:
        new_text, provider = await _translate_en_it(meaning)
        if provider not in ("none", "skip") and new_text != meaning:
            meaning = new_text
            translated = True
            translator = provider
            source = f"{source}+translate"

    if meaning:
        return {
            "name": name,
            "meaning": meaning,
            "source": source,
            "translated": translated,
            "translator": translator,
        }

    return {
        "name": name,
        "meaning": None,
        "source": "none",
        "message": "Significato non trovato nel dizionario locale.",
        "translated": False,
        "translator": None,
    }


# ---------------------------------------------------------------------------
# Static PWA (stesso origin)
# ---------------------------------------------------------------------------
def _file(name: str) -> FileResponse:
    path = STATIC_DIR / name
    if not path.exists():
        raise HTTPException(404, f"{name} non trovato")
    return FileResponse(path)


if STATIC_DIR.is_dir():
    @app.get("/index.html")
    def serve_index():
        return _file("index.html")

    @app.get("/manifest.json")
    def serve_manifest():
        return _file("manifest.json")

    @app.get("/sw.js")
    def serve_sw():
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/name_meanings.json")
    def serve_name_json():
        return _file("name_meanings.json")

    icons_dir = STATIC_DIR / "icons"
    if icons_dir.is_dir():
        app.mount("/icons", StaticFiles(directory=str(icons_dir)), name="icons")

    @app.get("/app")
    def serve_app_alias():
        return _file("index.html")

