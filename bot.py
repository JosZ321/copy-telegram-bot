#!/usr/bin/env python3
"""
Telegram Channel Bot
Copies @o2tvseries_new -> @NewmovieandSeries0
Rewrites with Gemini + emojis
Stores state in GitHub Gist
Runs on Render Cron every 10 min
"""

import os
import json
import asyncio
import logging
import sys
from datetime import datetime
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
import google.generativeai as genai

# ─── LOGGING ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('bot')

# ─── CONFIG ─────────────────────────────────────────────────────
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['SESSION_STRING']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GIST_ID = os.environ.get('GIST_ID', '')

SOURCE = os.environ.get('SOURCE_CHANNEL', 'o2tvseries_new')
DEST = os.environ.get('DEST_CHANNEL', 'NewmovieandSeries0')

# ─── GEMINI ─────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def rewrite(text):
    if not text or not text.strip():
        return "🎬 New update!"
    
    prompt = f"""Rewrite this Telegram post with emojis, keep all info (titles, episodes, qualities, links). 
Output ONLY the rewritten post. No intro. Under 1000 chars.

{text}

Rewritten:"""
    
    try:
        log.info("Calling Gemini...")
        r = model.generate_content(prompt)
        out = r.text.strip().replace('```', '')
        if not any(ord(c) > 0x1F300 for c in out):
            out = "🎬 " + out
        log.info(f"Gemini done: {len(out)} chars")
        return out[:4096]
    except Exception as e:
        log.error(f"Gemini failed: {e}")
        return f"🎬 {text[:4000]}"

# ─── GIST STORAGE ───────────────────────────────────────────────
GIST_API = "https://api.github.com/gists"

def load_state():
    if not GIST_ID:
        log.warning("No GIST_ID, starting fresh")
        return {'last_msg_id': 0, 'total': 0}
    
    try:
        log.info(f"Loading state from Gist...")
        r = requests.get(
            f"{GIST_API}/{GIST_ID}", 
            headers={"Authorization": f"token {GITHUB_TOKEN}"}, 
            timeout=10
        )
        data = json.loads(r.json()['files']['bot_data.json']['content'])
        log.info(f"State loaded: last_msg_id={data.get('last_msg_id', 0)}")
        return data
    except Exception as e:
        log.error(f"Gist load failed: {e}")
        return {'last_msg_id': 0, 'total': 0}

def save_state(data):
    payload = {
        "description": "Bot state",
        "public": False,
        "files": {"bot_data.json": {"content": json.dumps(data, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        if GIST_ID:
            log.info(f"Saving state...")
            requests.patch(f"{GIST_API}/{GIST_ID}", json=payload, headers=headers, timeout=10)
            log.info("State saved")
        else:
            log.info("Creating new Gist...")
            r = requests.post(GIST_API, json=payload, headers=headers, timeout=10)
            new_id = r.json()['id']
            log.warning(f"NEW GIST: Add GIST_ID={new_id} to Render")
            print(f"\n{'='*60}")
            print(f"  ADD TO RENDER ENV: GIST_ID={new_id}")
            print(f"{'='*60}\n")
    except Exception as e:
        log.error(f"Gist save failed: {e}")

# ─── MAIN ─────────────────────────────────────────────────────
async def main():
    start = datetime.now()
    log.info("=" * 50)
    log.info(f"Bot start | @{SOURCE} -> @{DEST}")
    
    state = load_state()
    last_id = state.get('last_msg_id', 0)
    
    log.info("Connecting Telegram...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    log.info("Connected")
    
    log.info(f"Fetching messages (min_id={last_id})...")
    messages = await client.get_messages(SOURCE, limit=20, min_id=last_id)
    
    if not messages:
        log.info("No new messages")
        await client.disconnect()
        return
    
    log.info(f"Found {len(messages)} new messages")
    
    new_last = last_id
    copied = 0
    
    for msg in reversed(messages):
        if msg.id <= last_id:
            continue
        
        text = msg.text or msg.raw_text or ""
        preview = text[:60].replace('\n', ' ') + "..." if len(text) > 60 else text
        log.info(f"[{copied+1}/{len(messages)}] #{msg.id}: {preview}")
        
        new_text = rewrite(text) if text else "🎬 New update!"
        
        try:
            if msg.media:
                log.info(f"Sending #{msg.id} with media...")
                await client.send_file(DEST, file=msg.media, caption=new_text)
            else:
                log.info(f"Sending #{msg.id} text...")
                await client.send_message(DEST, new_text)
            
            copied += 1
            new_last = msg.id
            log.info(f"Posted #{msg.id}")
            await asyncio.sleep(3)
            
        except Exception as e:
            log.error(f"Failed #{msg.id}: {e}")
            new_last = msg.id
    
    if copied > 0:
        state['last_msg_id'] = new_last
        state['total'] = state.get('total', 0) + copied
        save_state(state)
    
    duration = (datetime.now() - start).seconds
    log.info(f"Done | Copied: {copied} | Time: {duration}s | Total: {state.get('total', 0)}")
    log.info("=" * 50)
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())