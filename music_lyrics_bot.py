"""
🎵 Music Lyrics Bot - To'liq versiya v3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Foydalanuvchi:
  - Til tanlash (uz/ru/en)
  - Audio → qo'shiq nomi + lyrics + mp3
  - /favorites  — sevimlilar
  - /history    — oxirgi 10 ta qo'shiq

Creator (/admin):
  - Foydalanuvchilar statistikasi
  - Top qo'shiqlar
  - Broadcast
  - Reklama matnini o'zgartirish
  - Foydalanuvchini bloklash/blokdan chiqarish

O'rnatish:
  pip install python-telegram-bot aiohttp yt-dlp

API kalitlar:
  TELEGRAM_BOT_TOKEN  → @BotFather
  ACR_ACCESS_KEY      → console.acrcloud.com
  ACR_ACCESS_SECRET   → console.acrcloud.com
  ACR_HOST            → console.acrcloud.com
  GENIUS_TOKEN        → genius.com/api-clients
  ADMIN_ID            → o'zingizning Telegram ID (@userinfobot)
"""

import io, hmac, hashlib, base64, time, logging, asyncio, re, json, os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from pathlib import Path

import aiohttp
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ACR_ACCESS_KEY    = os.getenv("ACR_ACCESS_KEY", "YOUR_ACR_ACCESS_KEY")
ACR_ACCESS_SECRET = os.getenv("ACR_ACCESS_SECRET", "YOUR_ACR_ACCESS_SECRET")
ACR_HOST          = os.getenv("ACR_HOST", "identify-eu-west-1.acrcloud.com")
GENIUS_TOKEN      = os.getenv("GENIUS_TOKEN", "YOUR_GENIUS_API_TOKEN")
ADMIN_ID          = int(os.getenv("ADMIN_ID", 123456789))

DB_FILE           = "bot_db.json"
HISTORY_LIMIT     = 10

# ══════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════
def load_db() -> dict:
    if Path(DB_FILE).exists():
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "users":      {},
        "searches":   [],
        "song_stats": {},
        "blocked":    [],
        "ad_text":    "🎵 @YourChannelName — eng zo'r musiqa kanali!",
    }

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ── Foydalanuvchi ─────────────────────────
def register_user(uid: int, username: str):
    db = load_db()
    uid_str = str(uid)
    if uid_str not in db["users"]:
        db["users"][uid_str] = {
            "username":     username,
            "lang":         "uz",
            "joined":       datetime.now().isoformat(),
            "search_count": 0,
            "favorites":    [],
            "history":      [],
        }
        save_db(db)

def is_blocked(uid: int) -> bool:
    db = load_db()
    return str(uid) in db.get("blocked", [])

def block_user(uid: int):
    db = load_db()
    uid_str = str(uid)
    if uid_str not in db["blocked"]:
        db["blocked"].append(uid_str)
    save_db(db)

def unblock_user(uid: int):
    db = load_db()
    uid_str = str(uid)
    if uid_str in db["blocked"]:
        db["blocked"].remove(uid_str)
    save_db(db)

# ── Til ───────────────────────────────────
def get_lang(uid: int) -> str:
    db = load_db()
    return db["users"].get(str(uid), {}).get("lang", "uz")

def set_lang(uid: int, lang: str):
    db = load_db()
    uid_str = str(uid)
    if uid_str not in db["users"]:
        db["users"][uid_str] = {"lang": lang, "joined": datetime.now().isoformat(),
                                 "search_count": 0, "favorites": [], "history": []}
    else:
        db["users"][uid_str]["lang"] = lang
    save_db(db)

# ── Tarix ─────────────────────────────────
def add_to_history(uid: int, title: str, artist: str):
    db = load_db()
    uid_str = str(uid)
    if uid_str not in db["users"]:
        return
    entry = {"title": title, "artist": artist, "time": datetime.now().isoformat()}
    history = db["users"][uid_str].get("history", [])
    history.insert(0, entry)
    db["users"][uid_str]["history"] = history[:HISTORY_LIMIT]
    save_db(db)

def get_history(uid: int) -> list:
    db = load_db()
    return db["users"].get(str(uid), {}).get("history", [])

# ── Sevimlilar ────────────────────────────
def add_favorite(uid: int, title: str, artist: str) -> bool:
    db = load_db()
    uid_str = str(uid)
    if uid_str not in db["users"]:
        return False
    entry = {"title": title, "artist": artist}
    favs  = db["users"][uid_str].get("favorites", [])
    # Takrorlanmaslik
    for f in favs:
        if f["title"] == title and f["artist"] == artist:
            return False
    favs.append(entry)
    db["users"][uid_str]["favorites"] = favs
    save_db(db)
    return True

def remove_favorite(uid: int, index: int) -> bool:
    db = load_db()
    uid_str = str(uid)
    favs = db["users"].get(uid_str, {}).get("favorites", [])
    if 0 <= index < len(favs):
        favs.pop(index)
        db["users"][uid_str]["favorites"] = favs
        save_db(db)
        return True
    return False

def get_favorites(uid: int) -> list:
    db = load_db()
    return db["users"].get(str(uid), {}).get("favorites", [])

# ── Statistika ────────────────────────────
def log_search(uid: int, title: str, artist: str, success: bool):
    db = load_db()
    uid_str = str(uid)
    if uid_str in db["users"]:
        db["users"][uid_str]["search_count"] = db["users"][uid_str].get("search_count", 0) + 1
    db["searches"].append({
        "uid": uid, "title": title, "artist": artist,
        "success": success, "time": datetime.now().isoformat(),
    })
    if success and title:
        key = f"{artist} - {title}"
        db["song_stats"][key] = db["song_stats"].get(key, 0) + 1
    save_db(db)

# ── Reklama ───────────────────────────────
def get_ad_text() -> str:
    return load_db().get("ad_text", "")

def set_ad_text(text: str):
    db = load_db()
    db["ad_text"] = text
    save_db(db)

# ══════════════════════════════════════════
#  TIL MATNLARI
# ══════════════════════════════════════════
TEXTS = {
    "uz": {
        "welcome":       "👋 Salom! Men musiqa botman.\n\n🎵 Audio yuboring — qo'shiq nomi, lyrics va mp3 olasiz!\n\n📌 Buyruqlar:\n/favorites — sevimlilar\n/history — tarix\n/start — til o'zgartirish",
        "choose_lang":   "🌐 Tilni tanlang:",
        "blocked":       "🚫 Siz bloklangansiz. Murojaat uchun: @admin",
        "send_audio":    "🎵 Audio yoki ovozli xabar yuboring!",
        "searching":     "🔍 Qo'shiq aniqlanmoqda...",
        "found":         "✅ Topildi!",
        "not_found":     "❌ Qo'shiq aniqlanmadi. Boshqa audio sinab ko'ring.",
        "no_lyrics":     "😔 Bu qo'shiqning matni topilmadi.",
        "downloading":   "⬇️ Mp3 yuklanmoqda...",
        "no_mp3":        "😔 Mp3 topilmadi.",
        "title":         "🎵 Qo'shiq",
        "artist":        "🎤 Ijrochi",
        "lyrics_lbl":    "📝 Lyrics",
        "too_long":      "⚠️ Matn uzun, bo'lib yuborilmoqda...",
        "error":         "⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.",
        "not_admin":     "❌ Siz admin emassiz.",
        "saved_fav":     "❤️ Sevimlilarga qo'shildi!",
        "already_fav":   "ℹ️ Bu qo'shiq allaqachon sevimlilarda!",
        "fav_empty":     "📭 Sevimlilar bo'sh. Audio yuboring va ❤️ tugmasini bosing!",
        "fav_title":     "❤️ Sevimlilar",
        "fav_removed":   "🗑 O'chirildi!",
        "history_empty": "📭 Tarix bo'sh.",
        "history_title": "🕐 Oxirgi 10 ta qo'shiq",
    },
    "ru": {
        "welcome":       "👋 Привет! Я музыкальный бот.\n\n🎵 Отправьте аудио — получите название, текст и mp3!\n\n📌 Команды:\n/favorites — избранное\n/history — история\n/start — сменить язык",
        "choose_lang":   "🌐 Выберите язык:",
        "blocked":       "🚫 Вы заблокированы. Обратитесь к: @admin",
        "send_audio":    "🎵 Отправьте аудио или голосовое!",
        "searching":     "🔍 Определяю песню...",
        "found":         "✅ Найдено!",
        "not_found":     "❌ Не удалось определить. Попробуйте другое аудио.",
        "no_lyrics":     "😔 Текст не найден.",
        "downloading":   "⬇️ Загружаю mp3...",
        "no_mp3":        "😔 Mp3 не найден.",
        "title":         "🎵 Песня",
        "artist":        "🎤 Исполнитель",
        "lyrics_lbl":    "📝 Текст",
        "too_long":      "⚠️ Текст длинный, отправляю частями...",
        "error":         "⚠️ Произошла ошибка. Попробуйте снова.",
        "not_admin":     "❌ Вы не администратор.",
        "saved_fav":     "❤️ Добавлено в избранное!",
        "already_fav":   "ℹ️ Эта песня уже в избранном!",
        "fav_empty":     "📭 Избранное пусто. Отправьте аудио и нажмите ❤️!",
        "fav_title":     "❤️ Избранное",
        "fav_removed":   "🗑 Удалено!",
        "history_empty": "📭 История пуста.",
        "history_title": "🕐 Последние 10 песен",
    },
    "en": {
        "welcome":       "👋 Hi! I'm a music bot.\n\n🎵 Send audio — get song name, lyrics and mp3!\n\n📌 Commands:\n/favorites — saved songs\n/history — search history\n/start — change language",
        "choose_lang":   "🌐 Choose language:",
        "blocked":       "🚫 You are blocked. Contact: @admin",
        "send_audio":    "🎵 Send audio or voice message!",
        "searching":     "🔍 Identifying song...",
        "found":         "✅ Found!",
        "not_found":     "❌ Could not identify. Try another audio.",
        "no_lyrics":     "😔 Lyrics not found.",
        "downloading":   "⬇️ Downloading mp3...",
        "no_mp3":        "😔 Mp3 not found.",
        "title":         "🎵 Song",
        "artist":        "🎤 Artist",
        "lyrics_lbl":    "📝 Lyrics",
        "too_long":      "⚠️ Lyrics too long, sending in parts...",
        "error":         "⚠️ An error occurred. Please try again.",
        "not_admin":     "❌ You are not an admin.",
        "saved_fav":     "❤️ Added to favorites!",
        "already_fav":   "ℹ️ Already in favorites!",
        "fav_empty":     "📭 Favorites empty. Send audio and tap ❤️!",
        "fav_title":     "❤️ Favorites",
        "fav_removed":   "🗑 Removed!",
        "history_empty": "📭 History is empty.",
        "history_title": "🕐 Last 10 songs",
    },
}

def t(uid: int, key: str) -> str:
    lang = get_lang(uid)
    return TEXTS.get(lang, TEXTS["uz"]).get(key, TEXTS["uz"].get(key, key))

# ══════════════════════════════════════════
#  ACRCloud
# ══════════════════════════════════════════
async def identify_song(audio_bytes: bytes) -> dict | None:
    timestamp      = str(int(time.time()))
    string_to_sign = "\n".join(["POST", "/v1/identify", ACR_ACCESS_KEY, "audio", "1", timestamp])
    signature      = base64.b64encode(
        hmac.new(ACR_ACCESS_SECRET.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    url = f"https://{ACR_HOST}/v1/identify"
    logger.info(f"ACRCloud: {len(audio_bytes)} bayt audio => {url}")
    try:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("access_key",       ACR_ACCESS_KEY)
            form.add_field("sample_bytes",      str(len(audio_bytes)))
            form.add_field("timestamp",         timestamp)
            form.add_field("signature",         signature)
            form.add_field("data_type",         "audio")
            form.add_field("signature_version", "1")
            form.add_field("sample", audio_bytes, filename="sample.wav", content_type="audio/wav")
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                raw_text = await resp.text()
        data = json.loads(raw_text)
        status_code = data.get("status", {}).get("code")
        status_msg  = data.get("status", {}).get("msg", "")
        logger.info(f"ACRCloud javob: code={status_code}, msg={status_msg}")
        if status_code != 0:
            return None
        music  = data["metadata"]["music"][0]
        title  = music.get("title", "")
        artist = music["artists"][0]["name"] if music.get("artists") else ""
        logger.info(f"ACRCloud topdi: {artist} - {title}")
        return {"title": title, "artist": artist}
    except Exception as e:
        logger.error(f"ACRCloud xato: {e}")
        return None

# ══════════════════════════════════════════
#  LYRICS
# ══════════════════════════════════════════
async def get_lyrics_ovh(artist: str, title: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.lyrics.ovh/v1/{artist}/{title}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                lyrics = data.get("lyrics")
                return lyrics.strip() if lyrics else None
    except Exception as e:
        logger.warning(f"lyrics.ovh: {e}")
        return None

async def get_lyrics_genius(artist: str, title: str) -> str | None:
    headers = {
        "Authorization": f"Bearer {GENIUS_TOKEN}",
        "User-Agent": "Mozilla/5.0 (compatible)",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.genius.com/search",
                headers=headers,
                params={"q": f"{title} {artist}"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                raw = await resp.text()
            if not raw.strip():
                logger.warning("Genius: bo'sh javob (token noto'g'ri bo'lishi mumkin)")
                return None
            data = json.loads(raw)
            hits = data.get("response", {}).get("hits", [])
            if not hits:
                logger.info(f"Genius: topilmadi '{title} {artist}'")
                return None
            song_url = hits[0]["result"]["url"]
            logger.info(f"Genius URL: {song_url}")
            async with session.get(
                song_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                html = await resp.text()
        # 1-usul: window.__PRELOADED_STATE__ JSON dan lyrics olish (JS rendersiz ishlaydi)
        state_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*JSON\.parse\((.*?)\);', html, re.DOTALL)
        if state_match:
            try:
                state_json_str = json.loads(state_match.group(1))
                state = json.loads(state_json_str)
                lyrics = state.get("songPage", {}).get("lyricsData", {}).get("body", {}).get("plain", "")
                if lyrics and lyrics.strip():
                    logger.info(f"Genius __PRELOADED_STATE__ dan topildi: {len(lyrics)} belgi")
                    return lyrics.strip()
            except Exception as ex:
                logger.warning(f"Genius state parse: {ex}")
        # 2-usul: eski HTML div pattern
        patterns = [
            r'<div[^>]*data-lyrics-container[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*Lyrics__Container[^"]*"[^>]*>(.*?)</div>',
        ]
        lyrics = ""
        for pattern in patterns:
            parts = re.findall(pattern, html, re.DOTALL)
            if parts:
                for part in parts:
                    clean = re.sub(r'<br\s*/?>', "\n", part)
                    clean = re.sub(r'<[^>]+>', "", clean)
                    clean = re.sub(r'\[.*?\]', "", clean)
                    lyrics += clean + "\n"
                break
        lyrics = lyrics.strip()
        if lyrics:
            logger.info(f"Genius HTML dan topildi: {len(lyrics)} belgi")
            return lyrics
        logger.warning("Genius: hech bir usul ishlamadi")
        return None
    except Exception as e:
        logger.error(f"Genius xato: {e}")
        return None

async def get_lyrics_musixmatch(artist: str, title: str) -> str | None:
    """Musixmatch bepul API orqali lyrics olish"""
    APIKEY = "2005b5cd5a213e5f9a84a6e43e3b5d3a"  # bepul ochiq kalit
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.musixmatch.com/ws/1.1/matcher.lyrics.get",
                params={"q_track": title, "q_artist": artist, "apikey": APIKEY},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                raw = await resp.text()
        if not raw.strip():
            return None
        data = json.loads(raw)
        body = data.get("message", {}).get("body", {})
        # body ba'zan natija yo'qligida [] (list) bo'lib keladi
        if not isinstance(body, dict):
            return None
        lyrics_body = body.get("lyrics", {}).get("lyrics_body")
        if lyrics_body:
            # Musixmatch bepul versiyada oxirida reklama matni qo'shadi — uni olib tashlaymiz
            lyrics_body = lyrics_body.split("******* This Lyrics")[0].strip()
            logger.info(f"Musixmatch lyrics topildi: {len(lyrics_body)} belgi")
        return lyrics_body or None
    except Exception as e:
        logger.warning(f"Musixmatch: {e}")
        return None

async def find_lyrics(artist: str, title: str) -> str | None:
    logger.info(f"Lyrics qidirilmoqda: {artist} - {title}")
    # 1) lyrics.ovh
    lyrics = await get_lyrics_ovh(artist, title)
    if lyrics:
        logger.info("lyrics.ovh dan topildi!")
        return lyrics
    # 2) Genius
    lyrics = await get_lyrics_genius(artist, title)
    if lyrics:
        return lyrics
    # 3) Musixmatch (zaxira)
    lyrics = await get_lyrics_musixmatch(artist, title)
    if lyrics:
        return lyrics
    logger.info("Lyrics topilmadi (barcha manbalar)")
    return None

# ══════════════════════════════════════════
#  MP3 — YouTube (iOS bypass) → SoundCloud
# ══════════════════════════════════════════
async def _try_download(search_query: str, out_path: str, extra_opts: dict = {}) -> str | None:
    ydl_opts = {
        "format":         "bestaudio/best",
        "outtmpl":        out_path + ".%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3", "preferredquality": "128"}],
        "quiet":       True,
        "no_warnings": True,
        "noplaylist":  True,
        **extra_opts,
    }
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([search_query]))
        mp3 = out_path + ".mp3"
        return mp3 if Path(mp3).exists() else None
    except Exception as e:
        logger.warning(f"Download ({search_query[:40]}): {e}")
        return None

async def download_mp3(title: str, artist: str) -> str | None:
    query    = f"{artist} {title}"
    out_path = f"/tmp/{title}_{artist}".replace(" ", "_")[:60]

    # 1) YouTube — iOS player client (bot deteksiyasini chetlab o'tadi)
    mp3 = await _try_download(
        f"ytsearch1:{query} audio",
        out_path,
        {"extractor_args": {"youtube": {"player_client": ["ios"]}}}
    )
    if mp3:
        logger.info("YouTube iOS dan yuklab olindi!")
        return mp3

    # 2) YouTube — web_creator client
    mp3 = await _try_download(
        f"ytsearch1:{query}",
        out_path,
        {"extractor_args": {"youtube": {"player_client": ["web_creator"]}}}
    )
    if mp3:
        logger.info("YouTube web_creator dan yuklab olindi!")
        return mp3

    # 3) SoundCloud
    mp3 = await _try_download(f"scsearch1:{query}", out_path)
    if mp3:
        logger.info("SoundCloud dan yuklab olindi!")
        return mp3

    logger.info("MP3 topilmadi (barcha manbalar)")
    return None

# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════
async def send_long_text(update: Update, text: str, uid: int):
    if len(text) <= 4000:
        await update.message.reply_text(text)
    else:
        await update.message.reply_text(t(uid, "too_long"))
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i + 4000])
            await asyncio.sleep(0.3)

def admin_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm_users"),
        InlineKeyboardButton("🎵 Top qo'shiqlar",   callback_data="adm_top"),
    ], [
        InlineKeyboardButton("📊 Statistika",        callback_data="adm_stats"),
        InlineKeyboardButton("📣 Broadcast",         callback_data="adm_broadcast"),
    ], [
        InlineKeyboardButton("🚫 Bloklash",          callback_data="adm_block"),
        InlineKeyboardButton("✅ Blokdan chiqarish", callback_data="adm_unblock"),
    ], [
        InlineKeyboardButton("📢 Reklama",           callback_data="adm_ad"),
    ]])

# ══════════════════════════════════════════
#  FOYDALANUVCHI HANDLERLARI
# ══════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    register_user(uid, username)
    keyboard = [[
        InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang_uz"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]]
    await update.message.reply_text(
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    lang = {"lang_uz": "uz", "lang_ru": "ru", "lang_en": "en"}.get(query.data, "uz")
    set_lang(uid, lang)
    await query.edit_message_text(TEXTS[lang]["welcome"])

async def cmd_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    if is_blocked(uid):
        await update.message.reply_text(t(uid, "blocked"))
        return
    favs = get_favorites(uid)
    if not favs:
        await update.message.reply_text(t(uid, "fav_empty"))
        return
    lines    = [f"{i+1}. 🎵 {f['title']} — {f['artist']}" for i, f in enumerate(favs)]
    keyboard = [[InlineKeyboardButton(f"🗑 {i+1}-ni o'chirish", callback_data=f"delfav_{i}")]
                for i in range(len(favs))]
    await update.message.reply_text(
        f"{t(uid, 'fav_title')}:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    if is_blocked(uid):
        await update.message.reply_text(t(uid, "blocked"))
        return
    hist = get_history(uid)
    if not hist:
        await update.message.reply_text(t(uid, "history_empty"))
        return
    lines = [f"{i+1}. 🎵 {h['title']} — {h['artist']}\n    🕐 {h['time'][:10]}"
             for i, h in enumerate(hist)]
    await update.message.reply_text(f"{t(uid, 'history_title')}:\n\n" + "\n".join(lines))

async def fav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data.startswith("addfav_"):
        parts  = query.data[7:].split("|", 1)
        title  = parts[0]
        artist = parts[1] if len(parts) > 1 else ""
        added  = add_favorite(uid, title, artist)
        await query.answer(t(uid, "saved_fav") if added else t(uid, "already_fav"), show_alert=True)

    elif query.data.startswith("delfav_"):
        index = int(query.data[7:])
        remove_favorite(uid, index)
        # Ro'yxatni yangilash
        favs = get_favorites(uid)
        if not favs:
            await query.edit_message_text(t(uid, "fav_empty"))
        else:
            lines    = [f"{i+1}. 🎵 {f['title']} — {f['artist']}" for i, f in enumerate(favs)]
            keyboard = [[InlineKeyboardButton(f"🗑 {i+1}-ni o'chirish", callback_data=f"delfav_{i}")]
                        for i in range(len(favs))]
            await query.edit_message_text(
                f"{t(uid, 'fav_title')}:\n\n" + "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    if is_blocked(uid):
        await update.message.reply_text(t(uid, "blocked"))
        return

    audio = update.message.audio or update.message.voice or update.message.document
    if not audio:
        await update.message.reply_text(t(uid, "send_audio"))
        return

    msg = await update.message.reply_text(t(uid, "searching"))

    try:
        file        = await context.bot.get_file(audio.file_id)
        buf         = io.BytesIO()
        await file.download_to_memory(buf)
        audio_bytes = buf.getvalue()

        song = await identify_song(audio_bytes)
        if not song:
            log_search(uid, "", "", False)
            await msg.edit_text(t(uid, "not_found"))
            return

        title  = song["title"]
        artist = song["artist"]
        log_search(uid, title, artist, True)
        add_to_history(uid, title, artist)

        header = f"{t(uid, 'found')}\n\n{t(uid, 'title')}: *{title}*\n{t(uid, 'artist')}: *{artist}*"
        await msg.edit_text(header, parse_mode="Markdown")

        # Sevimlilarga qo'shish tugmasi
        fav_key = f"addfav_{title}|{artist}"
        await update.message.reply_text(
            "➕ Sevimlilarga qo'shish:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❤️ Sevimlilarga", callback_data=fav_key)
            ]])
        )

        # Lyrics va mp3 parallel
        lyrics_task = asyncio.create_task(find_lyrics(artist, title))
        mp3_task    = asyncio.create_task(download_mp3(title, artist))

        await update.message.reply_text(t(uid, "downloading"))

        lyrics   = await lyrics_task
        mp3_path = await mp3_task

        if lyrics:
            await update.message.reply_text(f"*{t(uid, 'lyrics_lbl')}:*", parse_mode="Markdown")
            await send_long_text(update, lyrics, uid)
        else:
            await update.message.reply_text(t(uid, "no_lyrics"))

        if mp3_path and Path(mp3_path).exists():
            with open(mp3_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f, title=title, performer=artist,
                    caption=get_ad_text(),
                )
            os.remove(mp3_path)
        else:
            await update.message.reply_text(t(uid, "no_mp3"))

    except Exception as e:
        logger.error(f"handle_audio: {e}")
        await msg.edit_text(t(uid, "error"))

# ══════════════════════════════════════════
#  ADMIN HANDLERLARI
# ══════════════════════════════════════════
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text(t(uid, "not_admin"))
        return
    await update.message.reply_text("🔧 *Admin Panel*", parse_mode="Markdown",
                                     reply_markup=admin_keyboard())

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if uid != ADMIN_ID:
        return

    db   = load_db()
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_back")]])

    if query.data == "adm_users":
        total = len(db["users"])
        langs = {}
        for u in db["users"].values():
            l = u.get("lang", "uz")
            langs[l] = langs.get(l, 0) + 1
        blocked_count = len(db.get("blocked", []))
        text = (f"👥 *Foydalanuvchilar*\n\n"
                f"Jami: *{total}* ta\n"
                f"🚫 Bloklangan: *{blocked_count}* ta\n\n"
                f"🇺🇿 O'zbek: {langs.get('uz', 0)}\n"
                f"🇷🇺 Русский: {langs.get('ru', 0)}\n"
                f"🇬🇧 English: {langs.get('en', 0)}")
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back)

    elif query.data == "adm_top":
        top = sorted(db.get("song_stats", {}).items(), key=lambda x: x[1], reverse=True)[:10]
        if not top:
            text = "📊 Hali qidiruvlar yo'q."
        else:
            lines = [f"{i+1}. {name} — {cnt} marta" for i, (name, cnt) in enumerate(top)]
            text  = "🎵 *Top 10 qo'shiqlar*\n\n" + "\n".join(lines)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back)

    elif query.data == "adm_stats":
        searches = db.get("searches", [])
        success  = sum(1 for s in searches if s.get("success"))
        text = (f"📊 *Statistika*\n\n"
                f"👥 Foydalanuvchilar: *{len(db['users'])}*\n"
                f"🔍 Jami qidiruvlar: *{len(searches)}*\n"
                f"✅ Muvaffaqiyatli: *{success}*\n"
                f"❌ Topilmadi: *{len(searches) - success}*")
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back)

    elif query.data == "adm_block":
        context.user_data["admin_mode"] = "block"
        await query.edit_message_text(
            "🚫 *Bloklash*\n\nFoydalanuvchi ID sini yuboring:\n_(Bekor qilish: /admin)_",
            parse_mode="Markdown"
        )

    elif query.data == "adm_unblock":
        blocked = db.get("blocked", [])
        if not blocked:
            await query.edit_message_text("✅ Bloklangan foydalanuvchilar yo'q.", reply_markup=back)
        else:
            lines = [f"• {uid_str}" for uid_str in blocked]
            context.user_data["admin_mode"] = "unblock"
            await query.edit_message_text(
                "✅ *Blokdan chiqarish*\n\nBloklangan IDlar:\n" + "\n".join(lines) +
                "\n\nChiqarish uchun ID yuboring:\n_(Bekor qilish: /admin)_",
                parse_mode="Markdown"
            )

    elif query.data == "adm_ad":
        context.user_data["admin_mode"] = "ad"
        current = get_ad_text()
        await query.edit_message_text(
            "📢 *Reklama*\n\nHozirgi:\n`" + current + "`\n\nYangi matnni yuboring:\n_(Bekor qilish: /admin)_",
            parse_mode="Markdown"
        )

    elif query.data == "adm_broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await query.edit_message_text(
            "📣 *Broadcast*\n\nBarcha userlarga yuboriladigan xabarni yozing:\n_(Bekor qilish: /admin)_",
            parse_mode="Markdown"
        )

    elif query.data == "adm_back":
        await query.edit_message_text("🔧 *Admin Panel*", parse_mode="Markdown",
                                       reply_markup=admin_keyboard())

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return
    mode = context.user_data.get("admin_mode")
    if not mode:
        return

    text = update.message.text
    context.user_data["admin_mode"] = None

    if mode == "ad":
        set_ad_text(text)
        await update.message.reply_text(f"✅ Reklama yangilandi!\n\n`{text}`", parse_mode="Markdown")

    elif mode == "block":
        try:
            target = int(text.strip())
            block_user(target)
            await update.message.reply_text(f"🚫 {target} bloklandi!")
        except ValueError:
            await update.message.reply_text("❌ Noto'g'ri ID format.")

    elif mode == "unblock":
        try:
            target = int(text.strip())
            unblock_user(target)
            await update.message.reply_text(f"✅ {target} blokdan chiqarildi!")
        except ValueError:
            await update.message.reply_text("❌ Noto'g'ri ID format.")

    elif mode == "broadcast":
        db = load_db()
        sent, fail = 0, 0
        for uid_str in db["users"]:
            if uid_str in db.get("blocked", []):
                continue
            try:
                await context.bot.send_message(int(uid_str), text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail += 1
        await update.message.reply_text(f"📣 Broadcast tugadi!\n✅ Yuborildi: {sent}\n❌ Xato: {fail}")

# ══════════════════════════════════════════
#  MAIN VA DUMMY SERVER (Render uchun)
# ══════════════════════════════════════════
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running")

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

def main():
    keep_alive()  # Render uchun port band qilish
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("favorites", cmd_favorites))
    app.add_handler(CommandHandler("history",   cmd_history))

    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(admin_callback,    pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(fav_callback,      pattern="^(addfav_|delfav_)"))

    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_input))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio))

    logger.info("🤖 Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
