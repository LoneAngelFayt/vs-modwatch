import os
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def run_scrape_all(session_factory) -> None:
    from app.db import Mod, ModVersion, VSVersion, get_setting
    from app.scraper import fetch_mod_page, fetch_vs_versions
    from app.notifier import notify

    db: Session = session_factory()
    try:
        try:
            vs_versions = await fetch_vs_versions()
            existing = {v.version for v in db.query(VSVersion).all()}
            db.query(VSVersion).update({"is_latest": False})
            for v in vs_versions:
                if v not in existing:
                    db.add(VSVersion(version=v))
            if vs_versions:
                latest = db.query(VSVersion).filter_by(version=vs_versions[0]).first()
                if latest:
                    latest.is_latest = True
            db.commit()
        except Exception:
            logger.exception("Failed to refresh VS version list")

        discord_url = os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url")
        apprise_url = os.getenv("APPRISE_URL") or get_setting(db, "apprise_url")

        for mod in db.query(Mod).all():
            try:
                data = await fetch_mod_page(mod.url)
                now = datetime.now(timezone.utc)
                if data.current_version and data.current_version != mod.current_version:
                    db.add(ModVersion(
                        mod_id=mod.id,
                        version=data.current_version,
                        vs_version=data.vs_version,
                        released_at=data.last_updated,
                    ))
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
            except Exception:
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
