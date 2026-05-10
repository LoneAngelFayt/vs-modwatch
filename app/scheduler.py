import os
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


async def _update_mod(db, mod, data, discord_url, apprise_url):
    """Update a single mod from scraped data. Handles initial seed and version changes."""
    from app.db import ModVersion
    from app.notifier import notify
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    existing_versions = {v.version for v in db.query(ModVersion).filter_by(mod_id=mod.id).all()}

    # Detect new current version
    is_new_version = bool(data.current_version and data.current_version != mod.current_version)

    # Seed all history entries not yet stored
    for entry in data.version_history:
        if entry["version"] and entry["version"] not in existing_versions:
            db.add(ModVersion(
                mod_id=mod.id,
                version=entry["version"],
                vs_version=entry.get("vs_version"),
                released_at=entry.get("released_at"),
            ))
            existing_versions.add(entry["version"])

    if is_new_version:
        mod.has_unread_update = True
        await notify(
            discord_url=discord_url,
            apprise_url=apprise_url,
            mod_name=mod.name or mod.url,
            new_version=data.current_version,
            vs_version=data.vs_version or "",
            side=data.side,
            mod_url=mod.url,
        )

    mod.name = data.name
    mod.current_version = data.current_version
    mod.vs_version = data.vs_version
    mod.side = data.side
    mod.last_updated = data.last_updated
    mod.last_checked = now
    db.commit()


async def run_scrape_one(session_factory, mod_id: int) -> None:
    from app.db import Mod, get_setting
    from app.scraper import fetch_mod_page

    db = session_factory()
    try:
        discord_url = os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url")
        apprise_url = os.getenv("APPRISE_URL") or get_setting(db, "apprise_url")
        mod = db.get(Mod, mod_id)
        if not mod:
            return
        try:
            data = await fetch_mod_page(mod.url)
            await _update_mod(db, mod, data, discord_url, apprise_url)
        except Exception:
            db.rollback()
            logger.exception("Failed to scrape mod %s", mod.url)
    finally:
        db.close()


async def run_scrape_all(session_factory) -> None:
    from app.db import Mod, VSVersion, get_setting
    from app.scraper import fetch_mod_page, fetch_vs_versions

    db = session_factory()
    try:
        try:
            vs_versions = await fetch_vs_versions()
            existing = {v.version for v in db.query(VSVersion).all()}
            if vs_versions:
                db.query(VSVersion).update({"is_latest": False})
                for v in vs_versions:
                    if v not in existing:
                        db.add(VSVersion(version=v))
                latest = db.query(VSVersion).filter_by(version=vs_versions[0]).first()
                if latest:
                    latest.is_latest = True
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to refresh VS version list")

        discord_url = os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url")
        apprise_url = os.getenv("APPRISE_URL") or get_setting(db, "apprise_url")

        for mod in db.query(Mod).all():
            try:
                data = await fetch_mod_page(mod.url)
                await _update_mod(db, mod, data, discord_url, apprise_url)
            except Exception:
                db.rollback()
                logger.exception("Failed to scrape mod %s", mod.url)
    finally:
        db.close()


def create_scheduler(session_factory, interval_hours: int = 6) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scrape_all, "interval", hours=interval_hours,
        args=[session_factory], id="scrape_all", replace_existing=True,
    )
    return scheduler
