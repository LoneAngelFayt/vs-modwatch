import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.db import Base, Mod, ModVersion, VSVersion


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    from app.main import app, get_db

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, TestingSession()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_dashboard_loads(client):
    c, db = client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "VS-ModWatch" in resp.text

def test_add_mod_invalid_url(client):
    c, db = client
    resp = c.post("/mods", data={"url": "not-a-url"}, headers={"HX-Request": "true"})
    assert resp.status_code == 422

def test_add_mod_already_tracked(client):
    c, db = client
    db.add(Mod(url="https://mods.vintagestory.at/testmod", name="Test"))
    db.commit()
    resp = c.post("/mods", data={"url": "https://mods.vintagestory.at/testmod"}, headers={"HX-Request": "true"})
    assert "already" in resp.text.lower()

def test_settings_page_loads(client):
    c, db = client
    resp = c.get("/settings")
    assert resp.status_code == 200

def test_save_settings(client):
    c, db = client
    resp = c.post("/settings", data={
        "discord_webhook_url": "",
        "apprise_url": "",
        "scrape_interval_hours": "6",
    })
    assert resp.status_code in (200, 303)

def test_delete_mod(client):
    c, db = client
    mod = Mod(url="https://mods.vintagestory.at/todelete", name="Gone")
    db.add(mod)
    db.commit()
    mod_id = mod.id
    resp = c.delete(f"/mods/{mod_id}")
    assert resp.status_code in (200, 204)
    db.expire_all()
    assert db.query(Mod).filter_by(id=mod_id).first() is None


def test_toggle_server_on(client):
    c, db = client
    mod = Mod(url="https://mods.vintagestory.at/toggle", on_server=False)
    db.add(mod); db.commit()
    resp = c.post(f"/mods/{mod.id}/toggle-server")
    assert resp.status_code == 200
    db.expire(mod)
    assert db.get(Mod, mod.id).on_server is True

def test_toggle_server_off(client):
    c, db = client
    mod = Mod(url="https://mods.vintagestory.at/toggle2", on_server=True)
    db.add(mod); db.commit()
    c.post(f"/mods/{mod.id}/toggle-server")
    db.expire(mod)
    assert db.get(Mod, mod.id).on_server is False

def test_patch_order(client):
    c, db = client
    mods = [Mod(url=f"https://mods.vintagestory.at/m{i}", sort_order=i) for i in range(3)]
    for m in mods: db.add(m)
    db.commit()
    ids = [m.id for m in mods]
    resp = c.patch("/mods/order", json={"ids": list(reversed(ids))})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Mod, ids[0]).sort_order == 2
    assert db.get(Mod, ids[2]).sort_order == 0

def test_download_redirect(client):
    c, db = client
    mod = Mod(url="https://mods.vintagestory.at/dl", current_version="v1.0.0", vs_version=">=1.19")
    db.add(mod); db.flush()
    db.add(ModVersion(
        mod_id=mod.id, version="v1.0.0", vs_version=">=1.19",
        download_url="https://mods.vintagestory.at/dl/mod_v1.0.0.zip",
        filename="mod_v1.0.0.zip",
    ))
    db.add(VSVersion(version="1.21.6", is_latest=True))
    db.commit()
    resp = c.get(f"/mods/{mod.id}/download?target=1.21.6", follow_redirects=False)
    assert resp.status_code == 302
    assert "mod_v1.0.0.zip" in resp.headers["location"]

def test_test_discord_no_url(client):
    c, db = client
    resp = c.post("/settings/test-discord")
    assert resp.status_code == 400
