import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.db import Base, Mod, VSVersion


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
    assert "ModWatch" in resp.text

def test_add_mod_invalid_url(client):
    c, db = client
    resp = c.post("/mods", data={"url": "not-a-url"})
    assert resp.status_code == 422

def test_add_mod_already_tracked(client):
    c, db = client
    db.add(Mod(url="https://mods.vintagestory.at/testmod", name="Test"))
    db.commit()
    resp = c.post("/mods", data={"url": "https://mods.vintagestory.at/testmod"})
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
