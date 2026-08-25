"""
middlewares.py — Telegram bot güvenlik katmanı.

AuthMiddleware:
  BaseMiddleware'den türetilmiş; her güncelleme (mesaj, callback, inline vb.)
  işlenmeden önce tetiklenir. Kullanıcı ID'si .env'deki ALLOWED_USER_IDS
  listesinde yoksa güncelleme sessizce düşürülür — hata mesajı bile gönderilmez.
  Bu yaklaşım:
    - Botu keşfeden yetkisiz kişilere var olduğunu bile belli etmez (stealth).
    - Middleware seviyesinde çalıştığı için handler'lara hiç ulaşılmaz.

Kullanım (bot.py):
    dp.update.middleware(AuthMiddleware())
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.config import settings

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Yetkilendirme middleware'i.

    Her Telegram güncellemesini yakalar ve gönderen kullanıcının
    ALLOWED_USER_IDS listesinde olup olmadığını kontrol eder.
    Yetkisiz erişimde güncelleme sessizce iptal edilir.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Update nesnesinden kullanıcı ID'sini çıkar
        user_id = self._extract_user_id(event, data)

        if user_id is None:
            # Kullanıcı ID'si alınamıyorsa (kanallar vb.) sessizce geç
            log.debug("AuthMiddleware: kullanıcı ID'si alınamadı, geçiliyor.")
            return await handler(event, data)

        if user_id not in settings.allowed_user_ids:
            log.warning(
                "AuthMiddleware: yetkisiz erişim engellendi. user_id=%d", user_id
            )
            # Handler çağrılmaz → güncelleme düşürülür
            return None

        log.debug("AuthMiddleware: erişim onaylandı. user_id=%d", user_id)
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject, data: dict[str, Any]) -> int | None:
        """
        Farklı güncelleme türlerinden kullanıcı ID'sini çıkarır.
        aiogram v3'te `data["event_from_user"]` genellikle dolu olur;
        yoksa Update nesnesini elle tarar.
        """
        # aiogram v3 handler data'sında zaten mevcut olabilir
        user = data.get("event_from_user")
        if user is not None:
            return user.id

        # Fallback: Update nesnesini tara
        if isinstance(event, Update):
            update: Update = event
            for attr in (
                "message",
                "edited_message",
                "channel_post",
                "edited_channel_post",
                "callback_query",
                "inline_query",
                "chosen_inline_result",
                "shipping_query",
                "pre_checkout_query",
                "my_chat_member",
                "chat_member",
            ):
                obj = getattr(update, attr, None)
                if obj is None:
                    continue
                # message / edited_message → .from_user
                from_user = getattr(obj, "from_user", None)
                if from_user is not None:
                    return from_user.id
                # callback_query → .from_user (zaten yukarıda yakalanır)

        return None