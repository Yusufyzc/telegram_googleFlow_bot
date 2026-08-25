"""
db.py — Asenkron SQLite veritabanı katmanı.

Kullanıcı çerez verileri (Google __Secure-1PSID) Fernet (AES-128-CBC) ile
şifreli olarak saklanır. Düz metin hiçbir zaman veritabanına yazılmaz.

Tablo: users
  user_id   INTEGER PRIMARY KEY   — Telegram kullanıcı ID'si
  cookie    TEXT NOT NULL         — Fernet ile şifrelenmiş çerez (base64)
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

log = logging.getLogger(__name__)

# ── Şifreleme yardımcıları ──────────────────────────────────────────────────

def _fernet() -> Fernet:
    """Her çağrıda Fernet nesnesi oluşturur (key .env'den okunur)."""
    return Fernet(settings.fernet_key.encode())


def encrypt_cookie(plaintext: str) -> str:
    """Çerezi şifreler ve base64 string olarak döndürür."""
    token: bytes = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_cookie(ciphertext: str) -> Optional[str]:
    """
    Şifrelenmiş çerezi çözer.
    Anahtar uyuşmazlığı veya bozuk veri durumunda None döndürür.
    """
    try:
        plaintext: bytes = _fernet().decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except (InvalidToken, Exception) as exc:
        log.error("Çerez şifre çözme hatası: %s", exc)
        return None


# ── Veritabanı bağlantısı ───────────────────────────────────────────────────

def get_db() -> aiosqlite.Connection:
    """
    DB bağlantısı döndürür — doğrudan `async with get_db() as db:` ile kullanılır.
    aiosqlite.connect() zaten bir async context manager döndürür, await gerekmez.
    """
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(str(db_path))


# ── Şema başlatma ────────────────────────────────────────────────────────────

async def init_db() -> None:
    """
    Tabloları asenkron olarak oluşturur. Uygulama başlangıcında bir kez çağrılır.
    IF NOT EXISTS ile idempotent'tir — mevcut tabloları silmez.
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                cookie     TEXT    NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    log.info("Veritabanı şeması hazır: %s", settings.db_path)


# ── CRUD operasyonları ───────────────────────────────────────────────────────

async def save_user_cookie(user_id: int, plaintext_cookie: str) -> None:
    """
    Kullanıcının çerezini şifreleyerek kaydeder veya günceller.
    Düz metin çerez bu fonksiyon dışına asla çıkmaz.
    """
    encrypted = encrypt_cookie(plaintext_cookie)
    async with get_db() as db:
        await db.execute("""
            INSERT INTO users (user_id, cookie, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                cookie     = excluded.cookie,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, encrypted))
        await db.commit()
    log.info("Kullanıcı çerezi kaydedildi: user_id=%d", user_id)


async def get_user_cookie(user_id: int) -> Optional[str]:
    """
    Kullanıcının şifrelenmiş çerezini veritabanından çeker ve çözer.
    Kayıt yoksa veya şifre çözme başarısız olursa None döndürür.
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT cookie FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    return decrypt_cookie(row["cookie"])


async def delete_user(user_id: int) -> bool:
    """
    Kullanıcıyı veritabanından siler.
    Silme işlemi gerçekleştiyse True, kayıt yoksa False döndürür.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM users WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        deleted = cursor.rowcount > 0

    if deleted:
        log.info("Kullanıcı silindi: user_id=%d", user_id)
    return deleted


async def user_exists(user_id: int) -> bool:
    """Kullanıcının veritabanında kayıtlı olup olmadığını kontrol eder."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM users WHERE user_id = ? LIMIT 1", (user_id,)
        )
        row = await cursor.fetchone()
    return row is not None