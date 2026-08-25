# Google Flow Telegram Bot

Google Flow (Veo) yapay zekası üzerinden video üretebilen, tamamen Dockerize edilmiş asenkron Telegram botu.

## Özellikler

- Telegram üzerinden `/video` komutuyla Google Flow'a video ürettirme
- VNC arayüzü ile Google hesabına tek seferlik giriş (tarayıcı otomasyonu)
- Kullanıcı yetkilendirme (sadece izin verilen Telegram ID'leri)
- Fernet (AES) ile şifreli cookie saklama
- Asenkron mimari (aiogram v3 + aiosqlite)
- Docker volume ile kalıcı veri saklama

## Gereksinimler

- Docker Desktop (Windows/Mac/Linux)
- Telegram Bot Token (@BotFather'dan alınır)
- Google hesabı (labs.google/fx/tools/flow erişimi olan)

## Kurulum

### 1. Ortam dosyasını hazırla

```bash
cp .env.example .env
```

`.env` dosyasını aç ve şu alanları doldur:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789,987654321
FERNET_KEY=your_fernet_key_here
FLOW_PROJECT_ID=your_project_uuid_here
VNC_PASSWORD=flowbot123
```

**Fernet key üretmek için:**
"fernet key generator" yazıp rastgele bir key üretebilirsiniz.

**Telegram User ID öğrenmek için:** Telegram'da @userinfobot'a yaz.

**Flow Project ID bulmak için:** [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow) adresine gir, bir proje aç. URL'deki UUID kısmını kopyala:
```
https://labs.google/fx/tools/flow/project/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

### 2. Docker'ı başlat

```bash
docker compose up -d --build
```

### 3. Google hesabına giriş yap (ilk kurulumda bir kez)

Tarayıcında şu adresi aç:
```
http://localhost:6080/vnc.html
```

Bağlan butonuna bas. VNC ekranında siyah masaüstü açılacak. **Sağ tıkla → "Open Chromium (Google Flow)"** seçeneğine tıkla. Chromium açılır ve Google Flow proje sayfasına gider. Google hesabına giriş yap. Giriş tamamlandıktan sonra bu adımı bir daha yapman gerekmez — profil Docker volume'unda kalıcı olarak saklanır.

> **Not:** Container silinirse (`docker compose down -v`) giriş bilgileri de silinir ve bu adımı tekrar yapman gerekir. Sadece `docker compose down` (volume silmeden) kullanırsan giriş bilgileri korunur.

### 4. Botu test et

Telegram'da bota yaz:

```
/start
/status
/video Gün batımında uçan bir kartal videosu
```

## Bot Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Botu başlat, karşılama mesajı |
| `/status` | Google oturum durumunu kontrol et |
| `/video <prompt>` | Video üret (üretim 2-5 dakika sürebilir) |
| `/help` | Yardım mesajı |

## Mimari

```
telegram_flow_bot2/
├── app/
│   ├── bot.py          — Telegram bot, komutlar, FSM
│   ├── config.py       — Ayarlar, .env okuma
│   ├── db.py           — SQLite veritabanı, Fernet şifreleme
│   ├── flow_api.py     — Google Flow Playwright otomasyonu
│   └── middlewares.py  — Yetkilendirme middleware
├── data/               — Docker volume (profil + veritabanı)
├── .env.example        — Örnek ortam dosyası
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── start.sh            — VNC + bot başlatma scripti
```

## Güvenlik

- Kullanıcı cookie'leri veritabanında düz metin olarak **saklanmaz** — Fernet (AES-128-CBC) ile şifrelenir
- Sadece `.env`'de tanımlı Telegram User ID'leri botu kullanabilir
- VNC erişimi şifre korumalıdır (`VNC_PASSWORD`)
- VNC portu (6080) sadece yerel ağda açık tutulmalıdır; internete açık sunucuda güvenlik duvarı ile kısıtlanmalıdır

## Sorun Giderme

**Bot cevap vermiyor:**
- `.env`'deki `ALLOWED_USER_IDS`'e kendi Telegram ID'ni ekle
- `docker compose logs -f bot` ile logları kontrol et

**Video üretilemedi hatası:**
- `http://localhost:6080/vnc.html` adresini aç, Chromium'da Google oturumunun açık olduğunu kontrol et
- Oturum kapandıysa tekrar giriş yap

**VNC bağlantı sorunu:**
- `docker compose restart bot` ile yeniden başlat
- Container'ın çalıştığını `docker ps` ile kontrol et