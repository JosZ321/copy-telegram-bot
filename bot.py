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
SOURCE = os.environ.get('SOURCE_CHANNEL', 'o2tvseries_new')
DEST = os.environ.get('DEST_CHANNEL', 'NewmovieandSeries0')
PORT = int(os.environ.get('PORT', 10000))
STATE_PREFIX = "__BOTSTATE__:"

# ─── GEMINI ─────────────────────────────────────────────────────
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

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

# ─── STATE (IN FILE - more reliable than Saved Messages) ───────
STATE_FILE = '/tmp/bot_state.json'  # /tmp is writable on Render

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                log.info(f"Loaded state from file: last={state.get('last')}, total={state.get('total')}")
                return state
    except Exception as e:
        log.error(f"State file load error: {e}")
    
    log.info("No state file found. Will create new state.")
    return None

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
        log.info(f"State saved: last={state['last']}, total={state['total']}")
    except Exception as e:
        log.error(f"State save failed: {e}")

# ─── BOT RUN ────────────────────────────────────────────────────
async def run_bot_once(force_test=False):
    log.info("=" * 50)
    log.info(f"STARTING | Source: @{SOURCE} → Dest: @{DEST}")
    
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    try:
        await client.start()
        log.info("Connected to Telegram")
    except Exception as e:
        log.error(f"Connection failed: {e}")
        return f"Connection failed: {e}"
    
    # Check destination
    try:
        dest = await client.get_entity(DEST)
        log.info(f"Destination OK: {dest.title}")
    except Exception as e:
        log.error(f"Destination error: {e}")
        await client.disconnect()
        return f"Cannot access dest: {e}"
    
    # Load or init state
    state = load_state()
    if state is None:
        # First run ever - get latest message ID from source
        try:
            latest = await client.get_messages(SOURCE, limit=1)
            if latest:
                last_id = latest[0].id
                log.info(f"First run. Starting from latest message #{last_id}")
                state = {'last': last_id, 'total': 0}
                save_state(state)
            else:
                log.info("Source channel is empty")
                await client.disconnect()
                return "Source channel empty"
        except Exception as e:
            log.error(f"Cannot read source: {e}")
            await client.disconnect()
            return f"Source error: {e}"
    
    last = state.get('last', 0)
    
    # FORCE TEST: Post a test message even if no new messages
    if force_test:
        log.info("FORCE TEST: Posting test message to destination...")
        try:
            test_msg = "🧪 Test message from bot! If you see this, posting works."
            await client.send_message(DEST, test_msg)
            log.info("✅ TEST POST SUCCESSFUL")
            await client.disconnect()
            return "Test post successful!"
        except Exception as e:
            log.error(f"❌ TEST POST FAILED: {e}")
            await client.disconnect()
            return f"Test post failed: {e}"
    
    # Fetch messages newer than last
    try:
        msgs = await client.get_messages(SOURCE, limit=20, min_id=last)
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        await client.disconnect()
        return f"Fetch failed: {e}"
    
    log.info(f"Fetched {len(msgs)} messages with min_id={last}")
    
    # Debug: Show all fetched message IDs
    if msgs:
        ids = [m.id for m in msgs]
        log.info(f"Message IDs found: {ids}")
    else:
        log.info("No messages with id > last_id. This means nothing new was posted.")
        # Still save state to confirm it works
        save_state(state)
        await client.disconnect()
        return "No new messages"
    
    new_last = last
    copied = 0
    
    for msg in reversed(msgs):
        if msg.id <= last:
            log.info(f"Skipping msg #{msg.id} (already processed)")
            continue
        
        text = msg.text or msg.raw_text or ""
        preview = text[:60].replace('\n', ' ') + "..." if len(text) > 60 else text
        log.info(f"Processing msg #{msg.id}: {preview}")
        
        new_text = rewrite(text) if text else "🎬 New update!"
        
        try:
            if msg.media:
                log.info(f"Sending with media...")
                sent = await client.send_file(DEST, file=msg.media, caption=new_text)
            else:
                log.info(f"Sending text...")
                sent = await client.send_message(DEST, new_text)
            
            copied += 1
            new_last = msg.id
            log.info(f"✅ POSTED: msg #{msg.id} → new msg #{sent.id}")
            await asyncio.sleep(3)
            
        except Exception as e:
            log.error(f"❌ FAILED msg #{msg.id}: {e}")
            new_last = msg.id  # Still advance to avoid loop
    
    # Save state
    if copied > 0:
        state['last'] = new_last
        state['total'] = state.get('total', 0) + copied
        save_state(state)
        log.info(f"Run complete: Copied {copied}, Total: {state['total']}")
    else:
        log.info("Nothing copied this run")
    
    await client.disconnect()
    log.info("=" * 50)
    return f"Copied {copied} messages"

# ─── FLASK ────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/health')
def health():
    def background():
        try:
            asyncio.run(run_bot_once())
        except Exception as e:
            log.error(f"Thread crash: {e}")
            log.error(traceback.format_exc())
    threading.Thread(target=background, daemon=True).start()
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.route('/run')
def manual_run():
    try:
        result = asyncio.run(run_bot_once())
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}, 500

@app.route('/test')
def test_post():
    """Force post a test message to verify permissions"""
    try:
        result = asyncio.run(run_bot_once(force_test=True))
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}, 500

@app.route('/')
def home():
    return {
        "bot": "telegram-channel-bot",
        "endpoints": {
            "/health": "Auto-run bot (background)",
            "/run": "Manual run with result",
            "/test": "Force test post to dest channel"
        }
    }

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("🚀 Starting up...")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
