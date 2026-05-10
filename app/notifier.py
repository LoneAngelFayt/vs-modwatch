import logging
import httpx
import apprise as apprise_lib

logger = logging.getLogger(__name__)


async def send_discord(
    webhook_url: str, mod_name: str, new_version: str,
    vs_version: str, side: str, mod_url: str,
) -> None:
    payload = {
        "embeds": [{
            "title": f"{mod_name} updated to {new_version}",
            "url": mod_url,
            "color": 0x3498DB,
            "fields": [
                {"name": "Version", "value": new_version, "inline": True},
                {"name": "VS Compatibility", "value": vs_version, "inline": True},
                {"name": "Side", "value": side.capitalize(), "inline": True},
            ],
        }]
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()


async def send_apprise(
    apprise_url: str, mod_name: str, new_version: str,
    vs_version: str, side: str, mod_url: str,
) -> None:
    ap = apprise_lib.Apprise()
    ap.add(apprise_url)
    ok = await ap.async_notify(
        title=f"{mod_name} updated to {new_version}",
        body=f"VS compatibility: {vs_version} | Side: {side}\n{mod_url}",
    )
    if not ok:
        logger.warning("Apprise notification failed for %s", mod_url)


async def notify(
    discord_url: str | None, apprise_url: str | None,
    mod_name: str, new_version: str, vs_version: str, side: str, mod_url: str,
) -> None:
    kwargs = dict(mod_name=mod_name, new_version=new_version,
                  vs_version=vs_version, side=side, mod_url=mod_url)
    if discord_url:
        try:
            await send_discord(webhook_url=discord_url, **kwargs)
        except Exception:
            logger.exception("Discord notification failed for %s", mod_url)
    if apprise_url:
        try:
            await send_apprise(apprise_url=apprise_url, **kwargs)
        except Exception:
            logger.exception("Apprise notification failed for %s", mod_url)
