import os
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db import DEFAULT_SETTINGS, Mod, ModVersion, VSVersion, get_setting
from app.notifier import notify
from app.scraper import fetch_mod_page, fetch_vs_versions
from app.versions import compat_level

logger = logging.getLogger(__name__)


async def _update_mod(db, mod, data, discord_url, apprise_url, discord_settings, notify_when, latest_vs_version):
    """Update a single mod from scraped data. Handles initial seed and version changes."""

    now = datetime.now(timezone.utc)

    # Only notify on a version change if there was already a tracked version.
    # mod.current_version is None on first scrape — don't fire a notification then.
    is_new_version = bool(
        data.current_version
        and mod.current_version is not None
        and data.current_version != mod.current_version
    )

    # Seed all history entries not yet stored; update is_tester on existing rows
    # that were seeded before the is_tester field existed.
    existing_rows = {v.version: v for v in db.query(ModVersion).filter_by(mod_id=mod.id).all()}
    existing_versions = set(existing_rows.keys())
    for entry in data.version_history:
        if not entry["version"]:
            continue
        if entry["version"] not in existing_versions:
            db.add(ModVersion(
                mod_id=mod.id,
                version=entry["version"],
                vs_version=entry.get("vs_version"),
                released_at=entry.get("released_at"),
                download_url=entry.get("download_url"),
                file_size=entry.get("file_size"),
                is_tester=entry.get("is_tester", False),
                filename=entry.get("filename"),
            ))
            existing_versions.add(entry["version"])
        elif entry.get("is_tester") and not existing_rows[entry["version"]].is_tester:
            # Backfill is_tester on rows seeded before this field was added
            existing_rows[entry["version"]].is_tester = True

    # Stable current entry: same logic as scraper — skip tester builds for mod-level fields
    stable_entry = next((e for e in data.version_history if not e.get("is_tester")), None)
    current_entry = stable_entry or (data.version_history[0] if data.version_history else None)

    compatible_with_latest = bool(
        data.vs_version and latest_vs_version and
        compat_level(data.vs_version, latest_vs_version) == "compatible"
    )

    if is_new_version:
        mod.has_unread_update = True
        await notify(
            discord_url=discord_url,
            apprise_url=apprise_url,
            notify_when=notify_when,
            compatible_with_latest=compatible_with_latest,
            discord_settings=discord_settings,
            mod_name=mod.name or mod.url,
            new_version=data.current_version,
            old_version=mod.current_version or "",
            vs_version=data.vs_version or "",
            side=data.side,
            mod_url=mod.url,
            filename=current_entry.get("filename") if current_entry else None,
            file_size=current_entry.get("file_size") if current_entry else None,
            latest_vs_version=latest_vs_version or "",
        )

    mod.name = data.name
    mod.current_version = data.current_version
    mod.vs_version = data.vs_version
    mod.side = data.side
    mod.last_updated = data.last_updated
    mod.last_checked = now
    if current_entry:
        mod.download_url = current_entry.get("download_url")
        mod.file_size = current_entry.get("file_size")
        mod.filename = current_entry.get("filename")
    db.commit()


async def run_scrape_one(session_factory, mod_id: int) -> None:
    db = session_factory()
    try:
        discord_url = os.getenv("DISCORD_WEBHOOK_URL") or get_setting(db, "discord_webhook_url")
        apprise_url = os.getenv("APPRISE_URL") or get_setting(db, "apprise_url")
        notify_when = get_setting(db, "notify_when", "always")

        # Populate VS version list if the table is empty (e.g. fresh database)
        if not db.query(VSVersion).first():
            try:
                vs_versions = await fetch_vs_versions()
                if vs_versions:
                    db.query(VSVersion).update({"is_latest": False})
                    for v in vs_versions:
                        if not db.query(VSVersion).filter_by(version=v).first():
                            db.add(VSVersion(version=v))
                    latest_row = db.query(VSVersion).filter_by(version=vs_versions[0]).first()
                    if latest_row:
                        latest_row.is_latest = True
                    db.commit()
            except Exception:
                logger.exception("Failed to populate VS version list")

        latest_vs_version = ""
        try:
            latest = db.query(VSVersion).filter_by(is_latest=True).first()
            if latest:
                latest_vs_version = latest.version
        except Exception:
            pass

        discord_settings = {
            key: get_setting(db, key, DEFAULT_SETTINGS[key])
            for key in DEFAULT_SETTINGS
            if key.startswith("discord_")
        }

        mod = db.get(Mod, mod_id)
        if not mod:
            return
        try:
            data = await fetch_mod_page(mod.url)
            await _update_mod(db, mod, data, discord_url, apprise_url, discord_settings, notify_when, latest_vs_version)
        except Exception:
            db.rollback()
            logger.exception("Failed to scrape mod %s", mod.url)
    finally:
        db.close()


async def run_scrape_all(session_factory) -> None:
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
        notify_when = get_setting(db, "notify_when", "always")

        # Get latest VS version
        latest_vs_version = ""
        try:
            latest = db.query(VSVersion).filter_by(is_latest=True).first()
            if latest:
                latest_vs_version = latest.version
        except Exception:
            pass

        # Build discord_settings dict
        discord_settings = {
            key: get_setting(db, key, DEFAULT_SETTINGS[key])
            for key in DEFAULT_SETTINGS
            if key.startswith("discord_")
        }

        for mod in db.query(Mod).all():
            try:
                data = await fetch_mod_page(mod.url)
                await _update_mod(db, mod, data, discord_url, apprise_url, discord_settings, notify_when, latest_vs_version)
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
