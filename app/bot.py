"""
bot.py — Ana Telegram bot modülü.

Komutlar:
  /start  — Karşılama mesajı
  /status — Chrome profil oturumunu kontrol eder
  /video  — Asenkron video üretimi başlatır

Mimari:
  Artık kullanıcı başına cookie yok. Paylaşılan Chrome profili
  (/data/chrome-profile/Default) tüm kullanıcılar için kullanılır.
  Yetkilendirme yalnızca ALLOWED_USER_IDS üzerinden yapılır.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile, Message

from app.config import settings
from app.db import init_db
from app.flow_api import generate_video, sanitize_prompt, verify_session
from app.middlewares import AuthMiddleware

log = logging.getLogger(__name__)

router = Router()

# ── Yardımcı mesajlar ─────────────────────────────────────────────────────────

WELCOME_TEXT = """
👋 <b>Google Flow Video Botu'na hoş geldiniz!</b>

Bu bot, Google Flow (Veo) yapay zekası aracılığıyla kısa videolar üretir.

<b>Komutlar:</b>
• /setup — Google hesabına giriş yapmak için VNC bağlantı bilgilerini göster
• /status — Oturum durumunu kontrol et
• /video &lt;açıklama&gt; — 10 saniyelik video üret

Örnek: <code>/video Kayseri sokaklarında koşan hamamböcekleri</code>
""".strip()


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT, parse_mode=ParseMode.HTML)


# ── /setup ────────────────────────────────────────────────────────────────────

@router.message(Command("setup"))
async def cmd_setup(message: Message) -> None:
    vnc_password = __import__("os").environ.get("VNC_PASSWORD", "flowbot123")
    await message.answer(
        "🖥️ <b>Google Hesabı Kurulumu</b>\n\n"
        "Botu kullanmadan önce Google Flow oturumu açman gerekiyor.\n\n"
        "<b>Adımlar:</b>\n"
        "1. Tarayıcında şu adresi aç:\n"
        "   <code>http://SUNUCU_IP:6080</code>\n\n"
        "2. Bağlantı ekranında şifreyi gir:\n"
        f"   <code>{vnc_password}</code>\n\n"
        "3. Açılan Chromium'da Google hesabına giriş yap\n"
        "4. <a href='https://labs.google/fx/tools/flow'>labs.google/fx/tools/flow</a> "
        "adresine git ve giriş yaptığını doğrula\n\n"
        "5. Tarayıcı sekmesini kapatabilirsin (giriş kalıcıdır)\n\n"
        "6. Telegram'da /status ile oturumu kontrol et\n\n"
        "⚠️ <i>SUNUCU_IP yerine Docker'ın çalıştığı makinenin IP adresini yaz.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── /status ───────────────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    checking_msg = await message.answer("🔍 Oturum durumu kontrol ediliyor...")

    try:
        is_valid = await verify_session()
        await checking_msg.delete()

        if is_valid:
            await message.answer("✅ Google Flow oturumu aktif ve geçerli.")
        else:
            await message.answer(
                "⚠️ Google oturumu geçersiz veya Chrome profili bulunamadı.\n"
                "Sunucu yöneticisiyle iletişime geçin."
            )
    except Exception:
        try:
            await checking_msg.delete()
        except Exception:
            pass
        await message.answer("❌ Oturum durumu kontrol edilemedi.")


# ── /video ────────────────────────────────────────────────────────────────────

@router.message(Command("video"))
async def cmd_video(message: Message) -> None:
    raw_prompt = (message.text or "").removeprefix("/video").strip()
    if not raw_prompt:
        await message.answer(
            "ℹ️ Kullanım: <code>/video &lt;video açıklaması&gt;</code>\n\n"
            "Örnek: <code>/video Gün batımında yüzen balıklar</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    prompt = sanitize_prompt(raw_prompt)
    if not prompt:
        await message.answer("❌ Geçersiz prompt. Farklı bir açıklama deneyin.")
        return

    info_msg = await message.answer(
        f"🎬 <b>Video üretimi başladı!</b>\n\n"
        f"📝 <i>{prompt[:100]}{'...' if len(prompt) > 100 else ''}</i>\n\n"
        f"⏱️ Bu işlem <b>3-8 dakika</b> sürebilir.\n"
        f"Hazır olduğunda videonuz buraya gönderilecek.",
        parse_mode=ParseMode.HTML,
    )

    asyncio.create_task(
        _produce_video(message, info_msg, message.from_user.id, prompt)
    )


async def _produce_video(
    message: Message,
    info_msg: Message,
    user_id: int,
    prompt: str,
) -> None:
    video_path: Path | None = None

    try:
        video_path = await generate_video(user_id, prompt)

        video_file = FSInputFile(str(video_path), filename="flow_video.mp4")
        await message.answer_video(
            video=video_file,
            caption=(
                f"✅ <b>Videonuz hazır!</b>\n"
                f"📝 <i>{prompt[:200]}</i>"
            ),
            parse_mode=ParseMode.HTML,
        )

        try:
            await info_msg.delete()
        except Exception:
            pass

        log.info("Video gönderildi: user_id=%d", user_id)

    except asyncio.TimeoutError:
        log.error("Video zaman aşımı: user_id=%d", user_id)
        try:
            await info_msg.edit_text(
                "⏰ Video üretimi zaman aşımına uğradı.\n"
                "Daha kısa bir prompt ile tekrar deneyin."
            )
        except Exception:
            pass

    except RuntimeError as exc:
        log.error("Video üretim hatası: user_id=%d, %s", user_id, exc)
        err_text = str(exc)
        if "oturum" in err_text.lower() or "profil" in err_text.lower():
            user_msg = "🔑 Google oturumu geçersiz. Sunucu yöneticisiyle iletişime geçin."
        else:
            user_msg = f"❌ Video üretilemedi.\n{err_text[:200]}"
        try:
            await info_msg.edit_text(user_msg)
        except Exception:
            pass

    except Exception as exc:
        log.exception("Beklenmeyen hata: user_id=%d", user_id)
        try:
            await info_msg.edit_text("❌ Beklenmeyen bir hata oluştu. Tekrar deneyin.")
        except Exception:
            pass

    finally:
        if video_path and video_path.exists():
            try:
                video_path.unlink()
                log.info("Geçici video silindi: %s", video_path)
            except Exception as exc:
                log.error("Dosya silinemedi: %s, %s", video_path, exc)


# ── Bilinmeyen mesajlar ───────────────────────────────────────────────────────

@router.message(~F.text.startswith("/"))
async def unknown_message(message: Message) -> None:
    await message.answer(
        "ℹ️ Kullanılabilir komutlar: /start, /status, /video"
    )


# ── Bot başlatma ──────────────────────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("Bot başlatılıyor...")

    await init_db()

    Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)

    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(AuthMiddleware())
    dp.include_router(router)

    log.info("İzin verilen kullanıcılar: %s", sorted(settings.allowed_user_ids))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        log.info("Bot kapatıldı.")


if __name__ == "__main__":
    asyncio.run(main())