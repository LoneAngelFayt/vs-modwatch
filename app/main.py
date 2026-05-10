import os
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import SessionLocal, init_db, Mod, ModVersion, VSVersion, get_setting, set_setting
from app.scheduler import create_scheduler, run_scrape_all
from app.versions import is_compatible

templates = Jinja2Templates(directory="app/templates")


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
    if is_compatible(mod.vs_version, target):
        return {"state": "compatible", "note": ""}
    history = db.query(ModVersion).filter_by(mod_id=mod.id).order_by(ModVersion.detected_at.desc()).all()
    for v in history:
        if v.vs_version and is_compatible(v.vs_version, target):
            return {"state": "outdated", "note": f"last compatible: {v.version}"}
    return {"state": "incompatible", "note": ""}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    interval = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    scheduler = create_scheduler(SessionLocal, interval_hours=interval)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DB, target: str = ""):
    vs_versions = db.query(VSVersion).order_by(VSVersion.version.desc()).all()
    if not target:
        latest = next((v for v in vs_versions if v.is_latest), None)
        target = latest.version if latest else (vs_versions[0].version if vs_versions else "")

    mods = db.query(Mod).order_by(Mod.added_at.desc()).all()
    for mod in mods:
        mod.has_unread_update = False
    db.commit()

    mod_data = [{"mod": mod, "compat": _compat_state(mod, target, db)} for mod in mods]

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "mod_cards_partial.html", {
            "mod_data": mod_data,
        })
    return templates.TemplateResponse(request, "dashboard.html", {
        "mod_data": mod_data,
        "vs_versions": vs_versions, "target": target,
    })


@app.post("/mods", response_class=HTMLResponse)
async def add_mod(request: Request, db: DB, url: str = Form(...)):
    url = url.strip()
    if not url.startswith("https://mods.vintagestory.at/"):
        return HTMLResponse("<p class='error'>URL must be from mods.vintagestory.at</p>", status_code=422)
    if db.query(Mod).filter_by(url=url).first():
        return HTMLResponse("<p class='error'>Mod is already being tracked</p>", status_code=200)
    mod = Mod(url=url)
    db.add(mod)
    db.commit()
    import asyncio
    asyncio.create_task(run_scrape_all(SessionLocal))
    return templates.TemplateResponse(request, "mod_card.html", {
        "item": {"mod": mod, "compat": {"state": "unknown", "note": ""}},
    })


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
    import asyncio
    asyncio.create_task(run_scrape_all(SessionLocal))
    return HTMLResponse("<span style='color:#94a3b8;font-size:.8rem;'>Refreshing…</span>")


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
    return templates.TemplateResponse(request, "settings.html", {
        "discord_webhook_url": os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url", ""),
        "apprise_url": os.getenv("APPRISE_URL") or get_setting(db, "apprise_url", ""),
        "scrape_interval_hours": os.getenv("SCRAPE_INTERVAL_HOURS") or get_setting(db, "scrape_interval_hours", "6"),
        "discord_from_env": bool(os.getenv("DISCORD_WEBHOOK_URL")),
        "apprise_from_env": bool(os.getenv("APPRISE_URL")),
        "interval_from_env": bool(os.getenv("SCRAPE_INTERVAL_HOURS")),
    })


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request, db: DB,
    discord_webhook_url: str = Form(""),
    apprise_url: str = Form(""),
    scrape_interval_hours: str = Form("6"),
):
    if not os.getenv("DISCORD_WEBHOOK_URL"):
        set_setting(db, "discord_webhook_url", discord_webhook_url or None)
    if not os.getenv("APPRISE_URL"):
        set_setting(db, "apprise_url", apprise_url or None)
    if not os.getenv("SCRAPE_INTERVAL_HOURS"):
        set_setting(db, "scrape_interval_hours", scrape_interval_hours)
    db.commit()
    return RedirectResponse("/settings", status_code=303)
