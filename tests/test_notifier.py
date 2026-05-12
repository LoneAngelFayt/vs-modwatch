import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.notifier import send_discord, send_apprise, notify, substitute_vars, build_discord_payload

APPRISE_KWARGS = dict(
    mod_name="Purposeful Storage",
    new_version="v1.3.2",
    vs_version=">=1.19",
    side="both",
    mod_url="https://mods.vintagestory.at/purposefulstorage",
)

NOTIFY_KWARGS = dict(
    discord_url=None, apprise_url=None,
    notify_when="always", compatible_with_latest=True,
    discord_settings={},
    mod_name="Test", new_version="v1.0", old_version="v0.9",
    vs_version=">=1.19", side="both", mod_url="https://mods.vintagestory.at/test",
    filename="test.zip", file_size=None, latest_vs_version="1.21.6",
)


def test_substitute_vars_basic():
    ctx = {"mod_name": "Purposeful Storage", "new_version": "v1.3.2"}
    assert substitute_vars("{mod_name} updated to {new_version}", ctx) == "Purposeful Storage updated to v1.3.2"


def test_substitute_vars_unknown_key_preserved():
    ctx = {"mod_name": "Test"}
    assert substitute_vars("{mod_name} — {unknown}", ctx) == "Test — {unknown}"


def test_build_discord_payload_default_fields():
    settings = {
        "discord_embed_title": "{mod_name} updated to {new_version}",
        "discord_embed_description": "",
        "discord_embed_color": "#3498DB",
        "discord_field_version_enabled": "true",
        "discord_field_version_label": "Version",
        "discord_field_version_value": "{new_version}",
        "discord_field_vs_enabled": "true",
        "discord_field_vs_label": "VS Compatibility",
        "discord_field_vs_value": "{vs_version}",
        "discord_field_side_enabled": "true",
        "discord_field_side_label": "Side",
        "discord_field_side_value": "{side}",
        "discord_field_compat_enabled": "true",
        "discord_field_compat_label": "Works on Latest",
        "discord_field_compat_value": "{compatible_with_latest}",
        "discord_custom_fields": "[]",
    }
    ctx = {
        "mod_name": "Purposeful Storage", "new_version": "v1.3.2",
        "old_version": "v1.3.1", "vs_version": ">=1.19",
        "side": "Client and Server", "mod_url": "https://mods.vintagestory.at/ps",
        "filename": "ps_v1.3.2.zip", "file_size": "1.8 MB",
        "latest_vs_version": "1.21.6", "compatible_with_latest": "Yes",
    }
    payload = build_discord_payload(settings, ctx)
    assert payload["embeds"][0]["title"] == "Purposeful Storage updated to v1.3.2"
    assert payload["embeds"][0]["color"] == 0x3498DB
    assert len(payload["embeds"][0]["fields"]) == 4


def test_build_discord_payload_disabled_field():
    settings = {
        "discord_embed_title": "{mod_name}",
        "discord_embed_description": "",
        "discord_embed_color": "#FF0000",
        "discord_field_version_enabled": "false",
        "discord_field_version_label": "Version",
        "discord_field_version_value": "{new_version}",
        "discord_field_vs_enabled": "false",
        "discord_field_vs_label": "VS",
        "discord_field_vs_value": "{vs_version}",
        "discord_field_side_enabled": "false",
        "discord_field_side_label": "Side",
        "discord_field_side_value": "{side}",
        "discord_field_compat_enabled": "false",
        "discord_field_compat_label": "Works on Latest",
        "discord_field_compat_value": "{compatible_with_latest}",
        "discord_custom_fields": "[]",
    }
    ctx = {"mod_name": "Test", "new_version": "v1", "old_version": "v0",
           "vs_version": ">=1.19", "side": "both", "mod_url": "https://x",
           "filename": "test.zip", "file_size": "1 MB",
           "latest_vs_version": "1.21.6", "compatible_with_latest": "Yes"}
    payload = build_discord_payload(settings, ctx)
    assert payload["embeds"][0]["fields"] == []


@pytest.mark.asyncio
async def test_send_discord_posts_payload():
    with patch("app.notifier.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=204, raise_for_status=MagicMock()))
        mock_cls.return_value = mock_client

        payload = {"embeds": [{"title": "Test", "color": 0x3498DB, "fields": []}]}
        await send_discord(webhook_url="https://discord.com/api/webhooks/123/abc", payload=payload)
        mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_apprise_calls_notify():
    with patch("app.notifier.apprise_lib.Apprise") as mock_cls:
        mock_ap = MagicMock()
        mock_ap.async_notify = AsyncMock(return_value=True)
        mock_cls.return_value = mock_ap

        await send_apprise(apprise_url="ntfy://mytopic", **APPRISE_KWARGS)

        mock_ap.add.assert_called_once_with("ntfy://mytopic")
        mock_ap.async_notify.assert_called_once()
        call_kwargs = mock_ap.async_notify.call_args.kwargs
        assert "Purposeful Storage" in call_kwargs.get("title", "")
        assert "ntfy://mytopic" in call_kwargs.get("title", "") or ">=1.19" in call_kwargs.get("body", "")


@pytest.mark.asyncio
async def test_notify_skips_when_not_configured():
    with patch("app.notifier.send_discord", new_callable=AsyncMock) as md, \
         patch("app.notifier.send_apprise", new_callable=AsyncMock) as ma:
        await notify(**NOTIFY_KWARGS)
        md.assert_not_called()
        ma.assert_not_called()


@pytest.mark.asyncio
async def test_notify_calls_both_when_configured():
    with patch("app.notifier.send_discord", new_callable=AsyncMock) as md, \
         patch("app.notifier.send_apprise", new_callable=AsyncMock) as ma:
        kwargs = {**NOTIFY_KWARGS, "discord_url": "https://discord.com/api/webhooks/1/x", "apprise_url": "ntfy://t"}
        await notify(**kwargs)
        md.assert_called_once()
        ma.assert_called_once()


@pytest.mark.asyncio
async def test_notify_skips_when_not_compatible_only():
    with patch("app.notifier.send_discord", new_callable=AsyncMock) as md:
        kwargs = {**NOTIFY_KWARGS, "discord_url": "https://discord.com/api/webhooks/1/x",
                  "notify_when": "compatible_only", "compatible_with_latest": False}
        await notify(**kwargs)
        md.assert_not_called()
