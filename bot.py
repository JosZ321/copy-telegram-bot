import os
import json
import asyncio
import logging
import threading
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

# ─── GEMINI (Direct HTTP - no heavy SDK) ────────────────────────
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

def rewrite(text):
    if not text or not text.strip():
        return "🎬 New update!"
    
    prompt = f"Rewrite with emojis, keep all info, no intro, under 1000 chars:\n\n{text}\n\nRewritten:"
    
    try:
        r = requests.post(GEMINI_URL, json={
            "contents": [{"parts": [{"text": prompt}]}],
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

# ─── STATE (Saved in your Telegram "Saved Messages") ────────────
async def load_state(client):
    msgs = await client.get_messages('me', search=STATE_PREFIX, limit=1)
    if msgs:
        try:
            return json.loads(msgs[0].text.split(STATE_PREFIX, 1)[1])
        except:
            pass
    latest = await client.get_messages(SOURCE, limit=1)
    if latest:
        log.info(f"No state. Starting from latest message #{latest[0].id}")
        return {'last': latest[0].id, 'total': 0}
    return {'last': 0, 'total': 0}

async def save_state(client, state):
    old = await client.get_messages('me', search=STATE_PREFIX, limit=10)
    for m in old:
        await m.delete()
    await client.send_message('me', f'{STATE_PREFIX}{json.dumps(state)}')

# ─── BOT RUN ────────────────────────────────────────────────────
bot_running = False

async def run_bot_once():
    global bot_running
    if bot_running:
        return "Already running"
    bot_running = True
    
    log.info("=" * 40)
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.start()
    
    state = await load_state(client)
    last = state.get('last', 0)
    log.info(f"Last message ID: {last}")
    
    msgs = await client.get_messages(SOURCE, limit=20, min_id=last)
    if not msgs:
        log.info("No new messages")
        await client.disconnect()
        bot_running = False
        return "No new messages"
    
    log.info(f"Found {len(msgs)} new messages")
    new_last = last
    copied = 0
    
    for msg in reversed(msgs):
        if msg.id <= last:
            continue
        text = msg.text or msg.raw_text or ""
        log.info(f"[{copied+1}/{len(msgs)}] #{msg.id}: {text[:50]}...")
        
        new_text = rewrite(text) if text else "🎬 New update!"
        try:
            if msg.media:
                await client.send_file(DEST, file=msg.media, caption=new_text)
            else:
                await client.send_message(DEST, new_text)
            copied += 1
            new_last = msg.id
            log.info(f"Posted #{msg.id}")
            await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Failed #{msg.id}: {e}")
            new_last = msg.id
    
    if copied:
        state['last'] = new_last
        state['total'] = state.get('total', 0) + copied
        await save_state(client, state)
        log.info(f"Total copied: {state['total']}")
    
    await client.disconnect()
    bot_running = False
    log.info("Done")
    return f"Copied {copied} messages"

# ─── FLASK WEB SERVER (UptimeRobot pings this) ─────────────────
app = Flask(__name__)

@app.route('/health')
def health():
    # Run bot in background thread so HTTP responds fast
    def background():
        asyncio.run(run_bot_once())
    threading.Thread(target=background).start()
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.route('/')
def home():
    return {"bot": "telegram-channel-bot", "status": "running"}

# ─── MAIN ───────────────────────────────────────────────────────
if __name__ == '__main__':
    # Run once immediately
    asyncio.run(run_bot_once())
    # Start web server (UptimeRobot keeps this alive)
    app.run(host='0.0.0.0', port=PORT)
