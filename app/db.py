import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/mods.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Mod(Base):
    __tablename__ = "mods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    current_version: Mapped[str | None] = mapped_column(String, nullable=True)
    vs_version: Mapped[str | None] = mapped_column(String, nullable=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    has_unread_update: Mapped[bool] = mapped_column(Boolean, default=False)
    on_server: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    versions: Mapped[list["ModVersion"]] = relationship(
        "ModVersion", back_populates="mod", cascade="all, delete-orphan"
    )


class ModVersion(Base):
    __tablename__ = "mod_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mod_id: Mapped[int] = mapped_column(Integer, ForeignKey("mods.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    vs_version: Mapped[str | None] = mapped_column(String, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    mod: Mapped["Mod"] = relationship("Mod", back_populates="versions")


class VSVersion(Base):
    __tablename__ = "vs_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str | None) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


DEFAULT_SETTINGS = {
    "allow_outdated_downloads": "false",
    "notify_when": "always",
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


def upgrade_db() -> None:
    """Add new columns to existing tables without dropping data (SQLite-safe)."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(mods)"))}
        new_cols = {
            "on_server": "BOOLEAN DEFAULT 0",
            "sort_order": "INTEGER DEFAULT 0",
            "download_url": "TEXT",
            "file_size": "INTEGER",
            "filename": "TEXT",
        }
        for col, typedef in new_cols.items():
            if col not in existing:
                conn.execute(sa.text(f"ALTER TABLE mods ADD COLUMN {col} {typedef}"))

        existing_mv = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(mod_versions)"))}
        new_mv_cols = {
            "download_url": "TEXT",
            "file_size": "INTEGER",
            "filename": "TEXT",
        }
        for col, typedef in new_mv_cols.items():
            if col not in existing_mv:
                conn.execute(sa.text(f"ALTER TABLE mod_versions ADD COLUMN {col} {typedef}"))
        conn.commit()


def seed_default_settings(db: Session) -> None:
    """Insert default settings that don't yet exist."""
    for key, value in DEFAULT_SETTINGS.items():
        if not db.get(Setting, key):
            db.add(Setting(key=key, value=value))
    db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    upgrade_db()
