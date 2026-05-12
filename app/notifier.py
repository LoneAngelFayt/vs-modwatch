import json
import logging
import httpx
import apprise as apprise_lib

logger = logging.getLogger(__name__)


def substitute_vars(template: str, ctx: dict) -> str:
    """Replace {key} placeholders with values from ctx. Unknown keys are left as-is."""
    import re
    def replace(m):
        return str(ctx.get(m.group(1), m.group(0)))
    return re.sub(r"\{(\w+)\}", replace, template)


def _hex_to_int(hex_str: str) -> int:
    return int(hex_str.lstrip("#"), 16)


def build_discord_payload(settings: dict, ctx: dict) -> dict:
    """Build a Discord webhook JSON payload from format settings and a context dict."""
    title = substitute_vars(settings.get("discord_embed_title", "{mod_name} updated to {new_version}"), ctx)
    description = substitute_vars(settings.get("discord_embed_description", ""), ctx).strip()
    color = _hex_to_int(settings.get("discord_embed_color", "#3498DB"))

    fields = []
    for key in ("version", "vs", "side", "compat"):
        if settings.get(f"discord_field_{key}_enabled", "true").lower() == "true":
            label = substitute_vars(settings.get(f"discord_field_{key}_label", key), ctx)
            value = substitute_vars(settings.get(f"discord_field_{key}_value", ""), ctx)
            fields.append({"name": label, "value": value, "inline": True})

    # Custom fields
    try:
        custom = json.loads(settings.get("discord_custom_fields", "[]"))
    except (json.JSONDecodeError, TypeError):
        custom = []
    for field in custom:
        if field.get("enabled", True):
            label = substitute_vars(field.get("label", ""), ctx)
            value = substitute_vars(field.get("value", ""), ctx)
            if label or value:
                fields.append({"name": label, "value": value, "inline": True})

    embed: dict = {"title": title, "url": ctx.get("mod_url", ""), "color": color, "fields": fields}
    if description:
        embed["description"] = description

    return {"embeds": [embed]}


async def send_discord(webhook_url: str, payload: dict) -> None:
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
    discord_url: str | None,
    apprise_url: str | None,
    notify_when: str,
    compatible_with_latest: bool,
    discord_settings: dict,
    mod_name: str, new_version: str, old_version: str,
    vs_version: str, side: str, mod_url: str,
    filename: str | None, file_size: int | None,
    latest_vs_version: str,
) -> None:
    if notify_when == "compatible_only" and not compatible_with_latest:
        logger.debug("Skipping notification for %s — not compatible with latest VS", mod_url)
        return

    def fmt_size(b: int | None) -> str:
        if not b:
            return "unknown"
        for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
            if b >= div:
                return f"{b/div:.1f} {unit}"
        return f"{b} B"

    ctx = {
        "mod_name": mod_name, "new_version": new_version, "old_version": old_version,
        "vs_version": vs_version, "side": side, "mod_url": mod_url,
        "filename": filename or "", "file_size": fmt_size(file_size),
        "latest_vs_version": latest_vs_version,
        "compatible_with_latest": "Yes" if compatible_with_latest else "No",
    }

    if discord_url:
        try:
            payload = build_discord_payload(discord_settings, ctx)
            await send_discord(discord_url, payload)
        except Exception:
            logger.exception("Discord notification failed for %s", mod_url)

    if apprise_url:
        try:
            await send_apprise(apprise_url, mod_name, new_version, vs_version, side, mod_url)
        except Exception:
            logger.exception("Apprise notification failed for %s", mod_url)
