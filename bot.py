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
from telethon.errors import ChatWriteForbiddenError, FloodWaitError

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

# ─── STATE ──────────────────────────────────────────────────────
async def load_state(client):
    msgs = await client.get_messages('me', search=STATE_PREFIX, limit=1)
    if msgs:
        try:
            state = json.loads(msgs[0].text.split(STATE_PREFIX, 1)[1])
            log.info(f"Loaded state: last={state.get('last')}, total={state.get('total')}")
            return state
        except Exception as e:
            log.error(f"State parse error: {e}")
    latest = await client.get_messages(SOURCE, limit=1)
    if latest:
        log.info(f"No state found. Starting from latest message #{latest[0].id}")
        return {'last': latest[0].id, 'total': 0}
    return {'last': 0, 'total': 0}

async def save_state(client, state):
    try:
        old = await client.get_messages('me', search=STATE_PREFIX, limit=10)
        for m in old:
            await m.delete()
        await client.send_message('me', f'{STATE_PREFIX}{json.dumps(state)}')
        log.info(f"State saved: last={state['last']}, total={state['total']}")
    except Exception as e:
        log.error(f"State save failed: {e}")

# ─── BOT RUN ────────────────────────────────────────────────────
async def run_bot_once():
    log.info("=" * 50)
    log.info(f"STARTING BOT RUN | Source: @{SOURCE} → Dest: @{DEST}")
    
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    try:
        await client.start()
        log.info("Connected to Telegram")
    except Exception as e:
        log.error(f"Failed to connect Telegram: {e}")
        return f"Connection failed: {e}"
    
    # Check if we can write to destination
    try:
        dest_entity = await client.get_entity(DEST)
        log.info(f"Destination channel found: {dest_entity.title}")
    except Exception as e:
        log.error(f"Cannot find destination channel @{DEST}: {e}")
        await client.disconnect()
        return f"Dest channel not found: {e}"
    
    state = await load_state(client)
    last = state.get('last', 0)
    
    try:
        msgs = await client.get_messages(SOURCE, limit=20, min_id=last)
    except Exception as e:
        log.error(f"Failed to fetch messages: {e}")
        await client.disconnect()
        return f"Fetch failed: {e}"
    
    if not msgs:
        log.info("No new messages found")
        await client.disconnect()
        return "No new messages"
    
    log.info(f"Found {len(msgs)} new messages")
    new_last = last
    copied = 0
    failed = 0
    
    for msg in reversed(msgs):
        if msg.id <= last:
            continue
        
        text = msg.text or msg.raw_text or ""
        preview = text[:60].replace('\n', ' ') + "..." if len(text) > 60 else text
        log.info(f"[{copied+1}/{len(msgs)}] Msg #{msg.id}: {preview}")
        
        new_text = rewrite(text) if text else "🎬 New update!"
        
        try:
            if msg.media:
                log.info(f"Sending msg #{msg.id} WITH MEDIA...")
                sent = await client.send_file(DEST, file=msg.media, caption=new_text)
                log.info(f"✅ MEDIA POSTED: msg #{msg.id} → new msg #{sent.id}")
            else:
                log.info(f"Sending msg #{msg.id} (text only)...")
                sent = await client.send_message(DEST, new_text)
                log.info(f"✅ TEXT POSTED: msg #{msg.id} → new msg #{sent.id}")
            
            copied += 1
            new_last = msg.id
            await asyncio.sleep(3)
            
        except ChatWriteForbiddenError:
            log.error(f"🚫 FORBIDDEN: You are not admin in @{DEST} or cannot post there!")
            failed += 1
            new_last = msg.id
        except FloodWaitError as e:
            log.warning(f"⏱️ FLOOD WAIT: must wait {e.seconds}s")
            failed += 1
            new_last = msg.id
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            log.error(f"❌ FAILED msg #{msg.id}: {type(e).__name__}: {e}")
            failed += 1
            new_last = msg.id
    
    if copied > 0:
        state['last'] = new_last
        state['total'] = state.get('total', 0) + copied
        await save_state(client, state)
    
    await client.disconnect()
    log.info(f"RUN COMPLETE | Copied: {copied} | Failed: {failed} | Total: {state.get('total', 0)}")
    log.info("=" * 50)
    return f"Copied {copied}, Failed {failed}"

# ─── FLASK ────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/health')
def health():
    log.info("🌐 /health ping received")
    def background():
        try:
            asyncio.run(run_bot_once())
        except Exception as e:
            log.error(f"BACKGROUND THREAD CRASHED: {e}")
            log.error(traceback.format_exc())
    threading.Thread(target=background, daemon=True).start()
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.route('/run')
def manual_run():
    """Manual trigger — waits for result"""
    log.info("🌐 /run manual trigger")
    try:
        result = asyncio.run(run_bot_once())
        return {"result": result}
    except Exception as e:
        log.error(f"MANUAL RUN CRASHED: {e}")
        return {"error": str(e), "trace": traceback.format_exc()}, 500

@app.route('/')
def home():
    return {"bot": "telegram-channel-bot", "endpoints": ["/health", "/run"]}

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    # Run once immediately on startup
    log.info("🚀 Starting up...")
    try:
        result = asyncio.run(run_bot_once())
        log.info(f"Startup run: {result}")
    except Exception as e:
        log.error(f"Startup run failed: {e}")
        log.error(traceback.format_exc())
    
    # Start web server
    log.info(f"Starting Flask on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
