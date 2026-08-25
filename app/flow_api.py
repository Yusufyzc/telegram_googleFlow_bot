"""
flow_api.py — Google Flow (Veo) video üretimi için asenkron sarmalayıcı.

Mimari:
  Paylaşılan Chrome profili (/data/chrome-profile) Playwright persistent
  context olarak headful modda (DISPLAY=:99 Xvfb) açılır.
  Google Flow AI asistan arayüzü üzerinden video üretilir.

Güvenlik:
  - Üretilen video dosyası caller tarafından silinmekle yükümlüdür.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from app.config import settings

log = logging.getLogger(__name__)

# ── Sabitler ────────────────────────────────────────────────────────────────

_PROMPT_MAX_LEN = 480
_UNSAFE_CHARS = re.compile(r"[<>{}\[\]|\\^`]")

# Paylaşılan Chrome profil dizini (Docker volume içinde)
CHROME_PROFILE_DIR = Path("/data/chrome-profile")

# Video üretim timeout (saniye)
_VIDEO_WAIT_TIMEOUT = 300


# ── Prompt temizleme ─────────────────────────────────────────────────────────

def sanitize_prompt(prompt: str) -> str:
    prompt = prompt.strip()
    prompt = re.sub(r"\s+", " ", prompt)
    prompt = _UNSAFE_CHARS.sub("", prompt)
    if len(prompt) > _PROMPT_MAX_LEN:
        prompt = prompt[:_PROMPT_MAX_LEN]
        log.warning("Prompt kesildi (%d karakter).", _PROMPT_MAX_LEN)
    return prompt


# ── Oturum doğrulama ─────────────────────────────────────────────────────────

async def verify_session() -> bool:
    """
    Chrome profilinin geçerli bir Google oturumu içerip içermediğini kontrol eder.
    """
    if not CHROME_PROFILE_DIR.exists():
        log.warning("Chrome profil dizini bulunamadı: %s", CHROME_PROFILE_DIR)
        return False

    try:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(CHROME_PROFILE_DIR),
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                env={"DISPLAY": ":99"},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            try:
                page = await ctx.new_page()
                await page.goto(
                    "https://labs.google/fx/tools/flow",
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
                await asyncio.sleep(3)
                final_url = page.url
                buttons = await page.evaluate(
                    "() => [...document.querySelectorAll('button')]"
                    ".map(b=>b.textContent.trim()).filter(t=>t)"
                )
                log.info("verify_session: url=%s, butonlar=%s", final_url[:80], buttons[:10])
            finally:
                await ctx.close()

        authenticated = "accounts.google.com" not in final_url
        return authenticated

    except Exception as exc:
        log.error("Oturum doğrulama hatası: %s", exc)
        return False


# ── Video indirme ────────────────────────────────────────────────────────────

# ── Flow UI etkileşimi ───────────────────────────────────────────────────────

async def _send_prompt(page, prompt: str) -> bool:
    """Prompt'u Flow AI asistan chat kutusuna gönder."""
    # Görünür contenteditable input'u bul
    input_el = page.locator("div[contenteditable][role='textbox']").first
    if await input_el.count() == 0:
        # Fallback: herhangi görünür contenteditable
        input_el = page.locator("div[contenteditable]").first

    if await input_el.count() == 0:
        log.warning("Prompt input bulunamadı")
        return False

    await input_el.click()
    await asyncio.sleep(0.5)
    await page.keyboard.press("Control+a")
    await asyncio.sleep(0.1)
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.1)
    # Karakterleri tek tek yaz
    for char in prompt:
        await page.keyboard.type(char)
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.8)
    # Enter ile gönder
    await page.keyboard.press("Enter")
    await asyncio.sleep(0.5)
    log.info("Prompt Enter ile gönderildi")
    return True


async def _handle_confirmation(page, timeout_s: float = 30) -> bool:
    """
    Flow AI onay diyaloğunu bekle ve 'Onayla ve bir daha sorma' seçeneğine tıkla.
    Onay seçenekleri <button> değil <div> elementi — tüm element tiplerini kontrol et.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    # Öncelik sırasına göre tıklanacak metinler
    confirm_texts = [
        "Onayla ve bir daha sorma",
        "Approve and don't ask again",
        "Don't ask again",
        "Onayla",
        "Approve",
        "Evet",
        "Yes",
    ]

    while asyncio.get_event_loop().time() < deadline:
        clicked = await page.evaluate(
            """(texts) => {
                for (const text of texts) {
                    // En küçük (leaf-e yakın) görünür elementi bul
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_ELEMENT,
                        null
                    );
                    let node;
                    while (node = walker.nextNode()) {
                        const rect = node.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        const t = node.textContent.trim();
                        if (t === text || t === text.replace('İ','I')) {
                            node.click();
                            return t.slice(0, 50);
                        }
                    }
                }
                return null;
            }""",
            confirm_texts,
        )
        if clicked:
            log.info("Onay tıklandı: '%s'", clicked)
            await asyncio.sleep(1)
            return True
        await asyncio.sleep(1)

    log.warning("Onay butonu bulunamadı (timeout)")
    return False


async def _wait_for_video(page, timeout_s: int = 300) -> Optional[str]:
    """
    Flow projesinde yeni video medyasının yüklenmesini bekle.
    Başlangıçtaki mevcut video src'lerini kaydeder, sadece yeni olanı döndürür.
    """
    log.info("Video üretimi bekleniyor (max %ds)...", timeout_s)
    deadline = asyncio.get_event_loop().time() + timeout_s

    # Başlangıçtaki mevcut video src'lerini kaydet
    existing_srcs = set(await page.evaluate("""
        () => {
            const srcs = new Set();
            document.querySelectorAll('video').forEach(v => {
                if (v.src) srcs.add(v.src);
                if (v.currentSrc) srcs.add(v.currentSrc);
            });
            document.querySelectorAll('video source').forEach(s => {
                if (s.src) srcs.add(s.src);
            });
            return [...srcs].filter(s => s.includes('google'));
        }
    """))
    log.info("Mevcut video sayısı: %d", len(existing_srcs))

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)

        # Tüm video src'lerini topla
        all_srcs = await page.evaluate("""
            () => {
                const srcs = new Set();
                document.querySelectorAll('video').forEach(v => {
                    if (v.src) srcs.add(v.src);
                    if (v.currentSrc) srcs.add(v.currentSrc);
                });
                document.querySelectorAll('video source').forEach(s => {
                    if (s.src) srcs.add(s.src);
                });
                return [...srcs].filter(s => s.includes('google'));
            }
        """)

        # Yeni (daha önce olmayan) video var mı?
        new_srcs = [s for s in all_srcs if s not in existing_srcs and s.strip()]
        if new_srcs:
            video_src = new_srcs[-1]
            log.info("Yeni video bulundu: %s...", video_src[:80])
            return video_src

        # Hata mesajı var mı?
        policy_error = await page.evaluate("""
            () => {
                const text = document.body.innerText.toLowerCase();
                return text.includes('violates our policy') ||
                       text.includes('content policy') ||
                       text.includes('unable to generate') ||
                       text.includes('couldn\\'t generate');
            }
        """)
        if policy_error:
            raise RuntimeError("İçerik politikası hatası — prompt reddedildi.")

        elapsed = timeout_s - (deadline - asyncio.get_event_loop().time())
        log.debug("Video bekleniyor... (%.0fs)", elapsed)

    raise RuntimeError(f"Video {timeout_s}s içinde üretilemedi (timeout).")


async def _get_video_download_url(page) -> Optional[str]:
    """
    Galeri'deki son videoya tıkla, indirme URL'sini al.
    """
    # Son medya elementine tıkla
    clicked = await page.evaluate("""
        () => {
            const items = [...document.querySelectorAll(
                'img[src*="getMediaUrlRedirect"], video[src*="google"]'
            )];
            if (items.length === 0) return false;
            items[items.length - 1].click();
            return true;
        }
    """)
    if clicked:
        await asyncio.sleep(2)

    # Download butonuna tıkla
    dl_clicked = await page.evaluate("""
        () => {
            const btns = [...document.querySelectorAll('button')];
            const dl = btns.find(b =>
                b.textContent.includes('download') ||
                b.textContent.includes('Download') ||
                b.textContent.toLowerCase().includes('indir')
            );
            if (dl) { dl.click(); return true; }
            return false;
        }
    """)
    if dl_clicked:
        await asyncio.sleep(1)

    # Network response'dan video URL'si yakala — page.on("response") ile
    # En son video src'yi döndür
    video_url = await page.evaluate("""
        () => {
            const vids = [...document.querySelectorAll('video')];
            for (const v of vids.reverse()) {
                const src = v.src || v.currentSrc || '';
                if (src.startsWith('http')) return src;
            }
            return null;
        }
    """)
    return video_url


# ── Ana video üretim fonksiyonu ──────────────────────────────────────────────

async def generate_video(
    user_id: int,
    prompt: str,
    *,
    timeout_s: Optional[int] = None,
) -> Path:
    """
    Paylaşılan Chrome profili üzerinden Flow AI asistan aracılığıyla video üretir.

    Akış:
      1. Persistent Chrome profiliyle Chromium başlat (headful, DISPLAY=:99)
      2. Proje sayfasına git
      3. Prompt'u gönder
      4. Onay diyaloğunu onayla
      5. Video üretilene bekle
      6. İndir ve yerel yolu döndür
    """
    _timeout = timeout_s or settings.video_timeout_s

    temp_dir = Path(settings.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / f"{user_id}_{uuid.uuid4().hex[:8]}.mp4"

    log.info("Video üretimi başlıyor: user_id=%d, prompt='%.60s...'", user_id, prompt)

    proj_url = f"https://labs.google/fx/tools/flow/project/{settings.flow_project_id}"

    pw_instance = None
    ctx = None

    try:
        pw_instance = await async_playwright().start()

        ctx = await pw_instance.chromium.launch_persistent_context(
            str(CHROME_PROFILE_DIR),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
            env={"DISPLAY": ":99"},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        page = await ctx.new_page()

        # Proje sayfasına git
        await page.goto(proj_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(4)

        final_url = page.url
        log.info("Sayfa: url=%s", final_url[:80])

        if "accounts.google.com" in final_url:
            raise RuntimeError("Google oturumu geçersiz. VNC'den Chrome profilini yenileyin.")

        # ── Adım 1: Prompt gönder ────────────────────────────────────────────
        ok = await _send_prompt(page, prompt)
        if not ok:
            raise RuntimeError("Prompt gönderilemedi.")
        await asyncio.sleep(3)

        # ── Adım 2: Onay diyaloğunu bekle ve onayla ─────────────────────────
        confirmed = await _handle_confirmation(page, timeout_s=30)
        if confirmed:
            log.info("Video üretimi onaylandı.")
        else:
            log.warning("Onay butonu bulunamadı, devam ediliyor...")

        # ── Adım 3: Video üretilene bekle ────────────────────────────────────
        video_src = await _wait_for_video(page, timeout_s=_timeout)

        if not video_src:
            raise RuntimeError("Video URL'si alınamadı.")

        # ── Adım 4: Playwright üzerinden indir (cookie otomatik gönderilir) ──
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = await page.request.get(video_src, timeout=120000)
        if response.status != 200:
            raise RuntimeError(f"Video indirme hatası: HTTP {response.status}")
        with open(output_path, "wb") as f:
            f.write(await response.body())
        log.info("Video indirildi: %s (%d bytes)", output_path.name, output_path.stat().st_size)

    except asyncio.TimeoutError:
        log.error("Video zaman aşımı: user_id=%d", user_id)
        raise
    except Exception as exc:
        log.exception("Video üretim hatası: user_id=%d, %s", user_id, exc)
        raise RuntimeError(f"Video üretilemedi: {exc}") from exc
    finally:
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass
        if pw_instance:
            try:
                await pw_instance.stop()
            except Exception:
                pass

    return output_path