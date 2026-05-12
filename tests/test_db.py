from app.db import Mod, ModVersion, VSVersion, get_setting, set_setting

def test_add_and_query_mod(db):
    mod = Mod(url="https://mods.vintagestory.at/testmod", name="Test Mod")
    db.add(mod)
    db.commit()
    result = db.query(Mod).filter_by(url="https://mods.vintagestory.at/testmod").one()
    assert result.name == "Test Mod"
    assert result.has_unread_update is False

def test_mod_version_cascade_delete(db):
    mod = Mod(url="https://mods.vintagestory.at/testmod2")
    db.add(mod)
    db.flush()
    db.add(ModVersion(mod_id=mod.id, version="1.0.0", vs_version=">=1.19"))
    db.commit()
    db.delete(mod)
    db.commit()
    assert db.query(ModVersion).count() == 0

def test_get_set_setting(db):
    set_setting(db, "discord_webhook_url", "https://discord.com/api/webhooks/123/abc")
    db.commit()
    assert get_setting(db, "discord_webhook_url") == "https://discord.com/api/webhooks/123/abc"

def test_get_setting_default(db):
    assert get_setting(db, "nonexistent", "fallback") == "fallback"

def test_mod_has_on_server(db):
    mod = Mod(url="https://mods.vintagestory.at/test")
    db.add(mod)
    db.commit()
    assert mod.on_server is False
    assert mod.sort_order == 0
    assert mod.download_url is None
    assert mod.file_size is None

def test_mod_version_has_download_fields(db):
    mod = Mod(url="https://mods.vintagestory.at/test2")
    db.add(mod)
    db.flush()
    v = ModVersion(
        mod_id=mod.id, version="v1.0.0",
        download_url="https://mods.vintagestory.at/dl/test_v1.0.0.zip",
        file_size=1024000,
        filename="test_v1.0.0.zip",
    )
    db.add(v)
    db.commit()
    assert db.query(ModVersion).filter_by(mod_id=mod.id).one().filename == "test_v1.0.0.zip"
