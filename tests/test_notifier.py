import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.notifier import send_discord, send_apprise, notify

KWARGS = dict(
    mod_name="Purposeful Storage",
    new_version="v1.3.2",
    vs_version=">=1.19",
    side="both",
    mod_url="https://mods.vintagestory.at/purposefulstorage",
)

@pytest.mark.asyncio
async def test_send_discord_posts_embed():
    with patch("app.notifier.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=204, raise_for_status=MagicMock()))
        mock_cls.return_value = mock_client

        await send_discord(webhook_url="https://discord.com/api/webhooks/123/abc", **KWARGS)

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args.kwargs.get("json", {})
        assert "embeds" in payload

@pytest.mark.asyncio
async def test_send_apprise_calls_notify():
    with patch("app.notifier.apprise_lib.Apprise") as mock_cls:
        mock_ap = MagicMock()
        mock_ap.async_notify = AsyncMock()
        mock_cls.return_value = mock_ap

        await send_apprise(apprise_url="ntfy://mytopic", **KWARGS)

        mock_ap.add.assert_called_once_with("ntfy://mytopic")
        mock_ap.async_notify.assert_called_once()

@pytest.mark.asyncio
async def test_notify_skips_when_not_configured():
    with patch("app.notifier.send_discord", new_callable=AsyncMock) as md, \
         patch("app.notifier.send_apprise", new_callable=AsyncMock) as ma:
        await notify(discord_url=None, apprise_url=None, **KWARGS)
        md.assert_not_called()
        ma.assert_not_called()

@pytest.mark.asyncio
async def test_notify_calls_both_when_configured():
    with patch("app.notifier.send_discord", new_callable=AsyncMock) as md, \
         patch("app.notifier.send_apprise", new_callable=AsyncMock) as ma:
        await notify(discord_url="https://discord.com/api/webhooks/1/x", apprise_url="ntfy://t", **KWARGS)
        md.assert_called_once()
        ma.assert_called_once()
