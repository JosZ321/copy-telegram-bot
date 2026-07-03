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

# ─── GIST STATE (Persistent across restarts) ──────────────────
GIST_API = "https://api.github.com/gists"

def load_state():
    if not GIST_ID or GIST_ID == 'value':
        log.warning("GIST_ID missing or invalid")
        return None
    try:
        r = requests.get(f"{GIST_API}/{GIST_ID}", 
                        headers={"Authorization": f"token {GITHUB_TOKEN}"}, 
                        timeout=15)
        if r.status_code == 200:
            content = r.json()['files']['bot_state.json']['content']
            state = json.loads(content)
            log.info(f"State loaded: last={state.get('last')}, total={state.get('total')}")
            return state
        else:
            log.error(f"Gist HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"Gist load failed: {e}")
    return None

def save_state(state):
    if not GIST_ID or GIST_ID == 'value':
        log.error("GIST_ID missing, cannot save")
        return
    payload = {
        "description": "Bot state",
        "public": False,
        "files": {"bot_state.json": {"content": json.dumps(state, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.patch(f"{GIST_API}/{GIST_ID}", json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            log.info(f"State saved: last={state['last']}, total={state['total']}")
        else:
            log.error(f"Gist save HTTP {r.status_code}")
    except Exception as e:
        log.error(f"Gist save failed: {e}")

def create_gist():
    """Create a new Gist and return its ID"""
    payload = {
        "description": "Bot state",
        "public": False,
        "files": {"bot_state.json": {"content": json.dumps({"last": 0, "total": 0}, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.post(GIST_API, json=payload, headers=headers, timeout=15)
        if r.status_code == 201:
            new_id = r.json()['id']
            log.warning(f"NEW GIST CREATED: {new_id}")
            log.warning("ADD THIS TO RENDER ENV VARS: GIST_ID=" + new_id)
            return new_id
    except Exception as e:
        log.error(f"Gist create failed: {e}")
    return None

# ─── BOT RUN ────────────────────────────────────────────────────
async def run_bot_once():
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
        # Try to create gist if missing
        global GIST_ID
        if not GIST_ID or GIST_ID == 'value':
            new_id = create_gist()
            if new_id:
                GIST_ID = new_id
                # Save to env for next time (won't persist on Render free, but we try)
                log.warning(f"Set GIST_ID={new_id} in Render env vars and redeploy!")
        
        latest = await client.get_messages(SOURCE, limit=1)
        if latest:
            last_id = latest[0].id
            log.info(f"First run. Starting from latest message #{last_id}")
            state = {'last': last_id, 'total': 0}
            save_state(state)
        else:
            log.info("Source channel is empty")
            await client.disconnect()
            return "Source empty"
    
    last = state.get('last', 0)
    
    # Fetch messages newer than last
    try:
        msgs = await client.get_messages(SOURCE, limit=20, min_id=last)
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        await client.disconnect()
        return f"Fetch failed: {e}"
    
    log.info(f"Fetched {len(msgs)} messages with min_id={last}")
    
    if not msgs:
        log.info("No new messages")
        save_state(state)  # Touch state to confirm it works
        await client.disconnect()
        return "No new messages"
    
    ids = [m.id for m in msgs]
    log.info(f"Message IDs found: {ids}")
    
    new_last = last
    copied = 0
    
    for msg in reversed(msgs):
        if msg.id <= last:
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
            new_last = msg.id
    
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

@app.route('/')
def home():
    return {"bot": "telegram-channel-bot", "endpoints": ["/health", "/run"]}

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("🚀 Starting up...")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
