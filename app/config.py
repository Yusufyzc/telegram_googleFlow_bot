"""
config.py — Ortam değişkenlerini yükler ve uygulama genelinde paylaşır.
Tüm ayarlar .env dosyasından okunur; eksik zorunlu değerler başlangıçta
hata fırlatır, böylece sorun erken yakalanır.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import FrozenSet

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Zorunlu ortam değişkenini okur; yoksa ValueError fırlatır."""
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(
            f"[config] Zorunlu ortam değişkeni eksik: {key}\n"
            f"Lütfen .env dosyanızı kontrol edin."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Settings:
    # ── Telegram ────────────────────────────────────────────────────────────
    telegram_token: str
    allowed_user_ids: FrozenSet[int]

    # ── Güvenlik ────────────────────────────────────────────────────────────
    fernet_key: str          # Fernet (AES-128-CBC) şifreleme anahtarı

    # ── Google Flow ─────────────────────────────────────────────────────────
    flow_project_id: str     # Google Flow proje UUID'si

    # ── Veritabanı ──────────────────────────────────────────────────────────
    db_path: str = field(default="/data/bot.db")

    # ── Video ───────────────────────────────────────────────────────────────
    video_timeout_s: int = field(default=300)
    temp_dir: str = field(default="/tmp/flow_videos")


def _parse_allowed_ids(raw: str) -> FrozenSet[int]:
    """
    'ALLOWED_USER_IDS=123,456,789' biçimini FrozenSet[int]'e dönüştürür.
    Boşluk toleranslı ve hatalı girişleri yoksayar.
    """
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


def load_settings() -> Settings:
    """
    Ortam değişkenlerinden Settings nesnesi oluşturur.
    Uygulama başlangıcında bir kez çağrılmalıdır.
    """
    return Settings(
        telegram_token=_require("TELEGRAM_BOT_TOKEN"),
        allowed_user_ids=_parse_allowed_ids(_require("ALLOWED_USER_IDS")),
        fernet_key=_require("FERNET_KEY"),
        flow_project_id=_require("FLOW_PROJECT_ID"),
        db_path=_optional("DB_PATH", "/data/bot.db"),
        video_timeout_s=int(_optional("VIDEO_TIMEOUT_S", "300")),
        temp_dir=_optional("TEMP_DIR", "/tmp/flow_videos"),
    )


# Uygulama genelinde paylaşılan tekil ayar nesnesi.
# Diğer modüller: `from app.config import settings`
settings: Settings = load_settings()