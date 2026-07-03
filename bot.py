import os
import json
import asyncio
import logging
import threading
from datetime import datetime
import requests
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
log = logging.getLogger()

# ─── CONFIG ─────────────────────────────────────────────────────
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION = os.environ['SESSION_STRING']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GIST_ID = os.environ.get('GIST_ID', '')

SOURCE = os.environ.get('SOURCE_CHANNEL', 'o2tvseries_new')
DEST = os.environ.get('DEST_CHANNEL', 'NewmovieandSeries0')
PORT = int(os.environ.get('PORT', 10000))

# ─── GEMINI ─────────────────────────────────────────────────────
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

def rewrite(text):
    if not text or not text.strip():
        return "🎬 New update!"
    try:
        r = requests.post(GEMINI_URL, json={
            "contents": [{"parts": [{"text": f"Rewrite with emojis, keep all info, no intro, under 1000 chars:\n\n{text}\n\nRewritten:"}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}
        }, timeout=30)
        r.raise_for_status()
        out = r.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('```', '')
        if not any(ord(c) > 0x1F300 for c in out):
            out = "🎬 " + out
        return out[:4096]
    except Exception as e:
        log.error(f"Gemini error: {e}")
        return f"🎬 {text[:4000]}"

# ─── GIST STATE ─────────────────────────────────────────────────
GIST_API = "https://api.github.com/gists"

def load_seen():
    if not GIST_ID or GIST_ID in ('', 'value'):
        return set()
    try:
        r = requests.get(f"{GIST_API}/{GIST_ID}", 
                        headers={"Authorization": f"token {GITHUB_TOKEN}"}, 
                        timeout=15)
        if r.status_code == 200:
            data = json.loads(r.json()['files']['bot_state.json']['content'])
            return set(data.get('seen', []))
    except Exception as e:
        log.error(f"Load error: {e}")
    return set()

def save_seen(seen):
    if not GIST_ID or GIST_ID in ('', 'value'):
        log.error("GIST_ID missing!")
        return False
    payload = {
        "description": "Bot state",
        "public": False,
        "files": {"bot_state.json": {"content": json.dumps({"seen": sorted(list(seen))}, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.patch(f"{GIST_API}/{GIST_ID}", json=payload, headers=headers, timeout=15)
        return r.status_code == 200
    except Exception as e:
        log.error(f"Save error: {e}")
    return False

# ─── SEEN SET (in-memory for speed) ───────────────────────────
seen_ids = load_seen()

# ─── COPY FUNCTION ────────────────────────────────────────────
async def copy_message(client, msg):
    """Copy a single message to destination"""
    global seen_ids
    
    if msg.id in seen_ids:
        log.info(f"Skipping #{msg.id} (already seen)")
        return
    
    text = msg.text or msg.raw_text or ""
    preview = text[:50].replace('\n', ' ') if text else "(no text)"
    log.info(f"New message #{msg.id}: {preview}")
    
    new_text = rewrite(text) if text else "🎬 New update!"
    
    try:
        if msg.media:
            sent = await client.send_file(DEST, file=msg.media, caption=new_text)
        else:
            sent = await client.send_message(DEST, new_text)
        
        seen_ids.add(msg.id)
        save_seen(seen_ids)
        log.info(f"✅ Copied to #{sent.id}")
        
    except Exception as e:
        log.error(f"❌ Failed: {e}")

# ─── TELEGRAM CLIENT (runs 24/7) ────────────────────────────────
async def start_monitoring():
    """Start Telegram client and listen for new messages"""
    log.info("=" * 50)
    log.info(f"Starting real-time monitor: @{SOURCE} -> @{DEST}")
    
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    
    @client.on(events.NewMessage(chats=SOURCE))
    async def handler(event):
        """Triggered INSTANTLY when new message arrives"""
        log.info(f"🔔 New message detected!")
        await copy_message(client, event.message)
    
    await client.start()
    log.info("✅ Monitoring started! Waiting for new messages...")
    
    # Keep running forever
    await client.run_until_disconnected()

# ─── FLASK (keeps Render awake) ───────────────────────────────
app = Flask(__name__)

@app.route('/health')
def health():
    return {
        "status": "ok",
        "monitoring": True,
        "seen_count": len(seen_ids),
        "time": datetime.now().isoformat()
    }

@app.route('/')
def home():
    return {
        "bot": "telegram-channel-bot",
        "mode": "real-time monitoring",
        "source": SOURCE,
        "dest": DEST,
        "seen_messages": len(seen_ids)
    }

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("🚀 Starting bot...")
    
    # Start Telegram monitor in background thread
    def run_monitor():
        asyncio.run(start_monitoring())
    
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    
    # Start Flask web server (keeps Render alive)
    log.info(f"Starting web server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
