import os
import json
import asyncio
import logging
import threading
import traceback
from datetime import datetime
import requests
from flask import Flask
from telethon import TelegramClient
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

# ─── GIST STATE (seen message IDs) ─────────────────────────────
GIST_API = "https://api.github.com/gists"

def load_seen():
    """Load set of seen message IDs from Gist"""
    if not GIST_ID or GIST_ID in ('', 'value'):
        log.warning("GIST_ID missing")
        return set()
    try:
        r = requests.get(f"{GIST_API}/{GIST_ID}", 
                        headers={"Authorization": f"token {GITHUB_TOKEN}"}, 
                        timeout=15)
        if r.status_code == 200:
            content = r.json()['files']['bot_state.json']['content']
            data = json.loads(content)
            seen = set(data.get('seen', []))
            log.info(f"Loaded {len(seen)} seen message IDs")
            return seen
    except Exception as e:
        log.error(f"Load error: {e}")
    return set()

def save_seen(seen):
    """Save set of seen message IDs to Gist"""
    if not GIST_ID or GIST_ID in ('', 'value'):
        log.error("GIST_ID missing, cannot save!")
        return False
    payload = {
        "description": "Bot state - seen message IDs",
        "public": False,
        "files": {"bot_state.json": {"content": json.dumps({"seen": sorted(list(seen))}, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.patch(f"{GIST_API}/{GIST_ID}", json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            log.info(f"Saved {len(seen)} seen IDs")
            return True
    except Exception as e:
        log.error(f"Save error: {e}")
    return False

# ─── BOT CORE ───────────────────────────────────────────────────
async def run_bot():
    log.info("=" * 50)
    log.info(f"Checking @{SOURCE} -> @{DEST}")
    
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    try:
        await client.start()
        log.info("Connected to Telegram")
    except Exception as e:
        return f"Connection failed: {e}"
    
    # Check destination
    try:
        dest = await client.get_entity(DEST)
        log.info(f"Destination OK: {dest.title}")
    except Exception as e:
        await client.disconnect()
        return f"Cannot access destination: {e}"
    
    # Load seen IDs
    seen = load_seen()
    
    # Get recent messages from source (last 20)
    try:
        msgs = await client.get_messages(SOURCE, limit=20)
    except Exception as e:
        await client.disconnect()
        return f"Cannot read source: {e}"
    
    log.info(f"Fetched {len(msgs)} recent messages")
    
    # Find unseen messages
    unseen = [m for m in msgs if m.id not in seen]
    log.info(f"Unseen messages: {len(unseen)}")
    
    if not unseen:
        log.info("Nothing new to copy")
        await client.disconnect()
        return "No new messages"
    
    # Copy unseen (oldest first)
    copied = 0
    for msg in reversed(unseen):
        text = msg.text or msg.raw_text or ""
        preview = text[:50].replace('\n', ' ') if text else "(no text)"
        log.info(f"Copying #{msg.id}: {preview}...")
        
        new_text = rewrite(text) if text else "🎬 New update!"
        
        try:
            if msg.media:
                sent = await client.send_file(DEST, file=msg.media, caption=new_text)
            else:
                sent = await client.send_message(DEST, new_text)
            
            # Mark as seen ONLY after successful post
            seen.add(msg.id)
            copied += 1
            log.info(f"✅ Posted as #{sent.id}")
            await asyncio.sleep(3)
            
        except Exception as e:
            log.error(f"❌ Failed #{msg.id}: {e}")
            # Don't mark as seen if failed - retry next time
    
    # Save updated seen list
    if copied > 0:
        save_seen(seen)
        log.info(f"Done! Copied {copied} new messages")
    else:
        log.info("Nothing copied")
    
    await client.disconnect()
    log.info("=" * 50)
    return f"Copied {copied} messages"

# ─── FLASK ──────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/health')
def health():
    def bg():
        try:
            asyncio.run(run_bot())
        except:
            log.error(traceback.format_exc())
    threading.Thread(target=bg, daemon=True).start()
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.route('/run')
def manual_run():
    try:
        result = asyncio.run(run_bot())
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}, 500

@app.route('/reset')
def reset_state():
    """Clear all seen IDs - will recopy everything"""
    if save_seen(set()):
        return {"result": "State cleared. Next run will copy all messages."}
    return {"error": "Failed to clear state"}, 500

@app.route('/')
def home():
    return {
        "bot": "telegram-channel-bot",
        "endpoints": {
            "/run": "Check and copy new messages",
            "/reset": "Clear seen list (recopy everything)",
            "/health": "Auto-check (UptimeRobot)"
        }
    }

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("🚀 Bot starting...")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
