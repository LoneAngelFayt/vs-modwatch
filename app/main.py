import asyncio
import logging
import os
import re as _re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Annotated
import httpx as _httpx
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from packaging.version import Version as PkgVersion
from sqlalchemy.orm import Session
from app.db import SessionLocal, init_db, Mod, ModVersion, VSVersion, get_setting, set_setting, seed_default_settings, DEFAULT_SETTINGS
from app.scheduler import create_scheduler, run_scrape_all, run_scrape_one
from app.versions import is_compatible, compat_level
from app.notifier import build_discord_payload, send_discord

import json as _json

# Route all uvicorn and app logs to stdout so Docker captures them correctly
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _log = logging.getLogger(_name)
    _log.handlers = [_stdout_handler]
    _log.propagate = False

templates = Jinja2Templates(directory="app/templates")

APP_VERSION = os.getenv("APP_VERSION", "dev")
_GITHUB_REPO = "LoneAngelFayt/vs-modwatch"
_version_cache: dict = {"latest": None, "checked_at": None}


async def _get_latest_github_version() -> str | None:
    """Return the latest release tag from GitHub, cached for 1 hour. Returns None on failure."""
    now = datetime.now(timezone.utc)
    if _version_cache["checked_at"] and (now - _version_cache["checked_at"]) < timedelta(hours=1):
        return _version_cache["latest"]
    try:
        async with _httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 200:
                tag = resp.json().get("tag_name", "").lstrip("v")
                _version_cache["latest"] = tag
                _version_cache["checked_at"] = now
                return tag
    except Exception:
        pass
    return None


def _validate_json_array(raw: str) -> str:
    """Return raw if it is a valid JSON array, otherwise return '[]'."""
    try:
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return raw
    except (ValueError, TypeError):
        pass
    return "[]"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DB = Annotated[Session, Depends(get_db)]


def _compat_state(mod: Mod, target: str, db: Session) -> dict:
    if not target or not mod.vs_version:
        return {"state": "unknown", "note": ""}
    level = compat_level(mod.vs_version, target)
    if level == "compatible":
        state = "installed" if mod.on_server else "compatible"
        return {"state": state, "note": ""}
    # warn or stale — check history for note
    history = db.query(ModVersion).filter_by(mod_id=mod.id).order_by(ModVersion.detected_at.desc()).all()
    for v in history:
        if v.vs_version and compat_level(v.vs_version, target) == "compatible":
            return {"state": level, "note": f"last compatible: {v.version}"}
    return {"state": level, "note": ""}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_default_settings(db)
        db.commit()
    finally:
        db.close()
    interval = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    scheduler = create_scheduler(SessionLocal, interval_hours=interval)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DB, target: str = "", view: str = "list", error: str = "", added: int = 0):
    vs_versions_raw = db.query(VSVersion).all()
    vs_versions = sorted(vs_versions_raw, key=lambda v: PkgVersion(v.version), reverse=True)
    if not target:
        latest = next((v for v in vs_versions if v.is_latest), None)
        target = latest.version if latest else (vs_versions[0].version if vs_versions else "")

    if not request.headers.get("HX-Request"):
        for mod in db.query(Mod).all():
            mod.has_unread_update = False
        db.commit()

    mods = db.query(Mod).order_by(Mod.sort_order.asc(), Mod.added_at.desc()).all()
    mod_data = [{"mod": mod, "compat": _compat_state(mod, target, db)} for mod in mods]
    allow_outdated_dl = get_setting(db, "allow_outdated_downloads", "false").lower() == "true"

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "mod_data": mod_data,
        "vs_versions": vs_versions, "target": target,
        "view": view, "allow_outdated_dl": allow_outdated_dl,
        "error": error, "added_id": added,
    })


@app.post("/mods", response_class=HTMLResponse)
async def add_mod(request: Request, db: DB, url: str = Form(...)):
    url = url.strip()
    is_htmx = bool(request.headers.get("HX-Request"))
    if not url.startswith("https://mods.vintagestory.at/"):
        if not is_htmx:
            return RedirectResponse("/?error=invalid_url", status_code=303)
        return HTMLResponse("<p class='error'>URL must be from mods.vintagestory.at</p>", status_code=422)
    if db.query(Mod).filter_by(url=url).first():
        if not is_htmx:
            return RedirectResponse("/", status_code=303)
        return HTMLResponse("<p class='error'>Mod is already being tracked</p>", status_code=200)
    mod = Mod(url=url)
    db.add(mod)
    db.commit()
    asyncio.create_task(run_scrape_one(SessionLocal, mod.id))
    if not is_htmx:
        return RedirectResponse(f"/?added={mod.id}", status_code=303)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = f"/?added={mod.id}"
    return response


@app.delete("/mods/{mod_id}", response_class=HTMLResponse)
async def delete_mod(mod_id: int, db: DB):
    mod = db.get(Mod, mod_id)
    if not mod:
        raise HTTPException(status_code=404)
    db.delete(mod)
    db.commit()
    return HTMLResponse("", status_code=200)


@app.post("/mods/{mod_id}/refresh", response_class=HTMLResponse)
async def refresh_mod(mod_id: int, db: DB):
    if not db.get(Mod, mod_id):
        raise HTTPException(status_code=404)
    asyncio.create_task(run_scrape_one(SessionLocal, mod_id))
    return HTMLResponse("<span style='color:#94a3b8;font-size:.8rem;'>Refreshing…</span>")


@app.post("/mods/{mod_id}/toggle-server", response_class=HTMLResponse)
async def toggle_server(mod_id: int, request: Request, db: DB, target: str = "", view: str = "list"):
    mod = db.get(Mod, mod_id)
    if not mod:
        raise HTTPException(status_code=404)
    mod.on_server = not mod.on_server
    db.commit()

    vs_versions_raw = db.query(VSVersion).all()
    vs_versions = sorted(vs_versions_raw, key=lambda v: PkgVersion(v.version), reverse=True)
    if not target:
        latest = next((v for v in vs_versions if v.is_latest), None)
        target = latest.version if latest else (vs_versions[0].version if vs_versions else "")

    allow_outdated_dl = get_setting(db, "allow_outdated_downloads", "false").lower() == "true"
    item = {"mod": mod, "compat": _compat_state(mod, target, db)}

    template_name = "mod_card.html" if view == "cards" else "list_row.html"
    return templates.TemplateResponse(template_name, {
        "request": request,
        "item": item,
        "target": target,
        "allow_outdated_dl": allow_outdated_dl,
    })


@app.patch("/mods/order")
async def update_order(db: DB, payload: dict):
    ids = payload.get("ids", [])
    for position, mod_id in enumerate(ids):
        if not isinstance(mod_id, int):
            continue
        mod = db.get(Mod, mod_id)
        if mod:
            mod.sort_order = position
    db.commit()
    return {"ok": True}


@app.get("/mods/{mod_id}/download")
async def download_mod(mod_id: int, db: DB, target: str = ""):
    mod = db.get(Mod, mod_id)
    if not mod:
        raise HTTPException(status_code=404)
    versions = db.query(ModVersion).filter_by(mod_id=mod_id).order_by(ModVersion.detected_at.desc()).all()
    best = None
    for v in versions:
        if not v.download_url:
            continue
        if not target or (v.vs_version and compat_level(v.vs_version, target) in ("compatible", "warn")):
            best = v
            break
    if not best:
        best = next((v for v in versions if v.download_url), None)
    if not best or not best.download_url:
        raise HTTPException(status_code=404, detail="No download available")
    return RedirectResponse(best.download_url, status_code=302)


@app.post("/settings/test-discord")
async def test_discord(db: DB):
    discord_url = os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url")
    if not discord_url:
        raise HTTPException(status_code=400, detail="No Discord webhook URL configured")
    discord_settings = {k: get_setting(db, k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS if k.startswith("discord_")}
    ctx = {
        "mod_name": "Example Mod", "new_version": "v2.0.0", "old_version": "v1.9.0",
        "vs_version": ">=1.19", "side": "Client and Server",
        "mod_url": "https://mods.vintagestory.at/examplemod",
        "filename": "examplemod_v2.0.0.zip", "file_size": "2.4 MB",
        "latest_vs_version": "1.21.6", "compatible_with_latest": "Yes",
    }
    try:
        payload = build_discord_payload(discord_settings, ctx)
        await send_discord(discord_url, payload)
        return {"ok": True, "message": "Test notification sent"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/mods/refresh-all", response_class=HTMLResponse)
async def refresh_all(db: DB):
    asyncio.create_task(run_scrape_all(SessionLocal))
    return HTMLResponse("<span style='color:#94a3b8;font-size:.8rem;'>Refreshing all…</span>")


@app.post("/settings/reset-discord-defaults", response_class=HTMLResponse)
async def reset_discord_defaults(db: DB):
    for key, val in DEFAULT_SETTINGS.items():
        if key.startswith("discord_"):
            set_setting(db, key, val)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.get("/mods/{mod_id}/history", response_class=HTMLResponse)
async def mod_history(mod_id: int, request: Request, db: DB):
    mod = db.get(Mod, mod_id)
    if not mod:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "mod_history.html", {
        "versions": mod.versions,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: DB):
    ctx = {
        "discord_webhook_url": os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url", ""),
        "apprise_url": os.getenv("APPRISE_URL") or get_setting(db, "apprise_url", ""),
        "scrape_interval_hours": os.getenv("SCRAPE_INTERVAL_HOURS") or get_setting(db, "scrape_interval_hours", "6"),
        "discord_from_env": bool(os.getenv("DISCORD_WEBHOOK_URL")),
        "apprise_from_env": bool(os.getenv("APPRISE_URL")),
        "interval_from_env": bool(os.getenv("SCRAPE_INTERVAL_HOURS")),
        "allow_outdated_downloads": get_setting(db, "allow_outdated_downloads", "false").lower() == "true",
        "notify_when": get_setting(db, "notify_when", "always"),
    }
    for key in DEFAULT_SETTINGS:
        if key.startswith("discord_"):
            ctx[key] = get_setting(db, key, DEFAULT_SETTINGS[key])
    latest = await _get_latest_github_version()
    ctx["app_version"] = APP_VERSION
    ctx["latest_version"] = latest or APP_VERSION
    ctx["is_latest"] = (latest is None) or (APP_VERSION == "dev") or (APP_VERSION == latest)
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request, db: DB,
    scrape_interval_hours: str = Form("6"),
    allow_outdated_downloads: str = Form("false"),
    notify_when: str = Form("always"),
    discord_webhook_url: str = Form(""),
    apprise_url: str = Form(""),
    discord_embed_title: str = Form("{mod_name} updated to {new_version}"),
    discord_embed_description: str = Form(""),
    discord_embed_color: str = Form("#3498DB"),
    discord_field_version_enabled: str = Form("false"),
    discord_field_version_label: str = Form("Version"),
    discord_field_version_value: str = Form("{new_version}"),
    discord_field_vs_enabled: str = Form("false"),
    discord_field_vs_label: str = Form("VS Compatibility"),
    discord_field_vs_value: str = Form("{vs_version}"),
    discord_field_side_enabled: str = Form("false"),
    discord_field_side_label: str = Form("Side"),
    discord_field_side_value: str = Form("{side}"),
    discord_field_compat_enabled: str = Form("false"),
    discord_field_compat_label: str = Form("Works on Latest"),
    discord_field_compat_value: str = Form("{compatible_with_latest}"),
    discord_custom_fields: str = Form("[]"),
):
    if not os.getenv("SCRAPE_INTERVAL_HOURS"):
        set_setting(db, "scrape_interval_hours", scrape_interval_hours)
    set_setting(db, "allow_outdated_downloads", "true" if allow_outdated_downloads == "on" else "false")
    set_setting(db, "notify_when", notify_when)
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        set_setting(db, "discord_webhook_url", discord_webhook_url or None)
    if not os.getenv("APPRISE_URL"):
        set_setting(db, "apprise_url", apprise_url or None)
    color_val = discord_embed_color.strip()
    if not _re.match(r'^#[0-9a-fA-F]{6}$', color_val):
        color_val = "#3498DB"
    for key, val in [
        ("discord_embed_title", discord_embed_title),
        ("discord_embed_description", discord_embed_description),
        ("discord_embed_color", color_val),
        ("discord_field_version_enabled", "true" if discord_field_version_enabled == "on" else "false"),
        ("discord_field_version_label", discord_field_version_label),
        ("discord_field_version_value", discord_field_version_value),
        ("discord_field_vs_enabled", "true" if discord_field_vs_enabled == "on" else "false"),
        ("discord_field_vs_label", discord_field_vs_label),
        ("discord_field_vs_value", discord_field_vs_value),
        ("discord_field_side_enabled", "true" if discord_field_side_enabled == "on" else "false"),
        ("discord_field_side_label", discord_field_side_label),
        ("discord_field_side_value", discord_field_side_value),
        ("discord_field_compat_enabled", "true" if discord_field_compat_enabled == "on" else "false"),
        ("discord_field_compat_label", discord_field_compat_label),
        ("discord_field_compat_value", discord_field_compat_value),
        ("discord_custom_fields", _validate_json_array(discord_custom_fields)),
    ]:
        set_setting(db, key, val)
    db.commit()
    return RedirectResponse("/settings", status_code=303)
