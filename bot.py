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

# Format a SMALL batch of shows (max ~10 episodes to stay under token limit)
BATCH_PROMPT = """Format these TV show episodes into a clean list.

Rules:
- Each show: "[Number]. [Emoji] [Show Name]"
- Episodes: "Season XX, Episode XX - [Date]" (stacked, no blank lines between)
- One blank line between different shows
- NO header, NO footer - just the list

Input:
{text}

Output:"""

def format_batch(text_batch):
    """Format one batch of shows via Gemini"""
    try:
        r = requests.post(GEMINI_URL, json={
            "contents": [{"parts": [{"text": BATCH_PROMPT.format(text=text_batch)}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
        }, timeout=30)
        r.raise_for_status()
        out = r.json()['candidates'][0]['content']['parts'][0].text.strip()
        out = out.replace('```', '').strip()
        return out
    except Exception as e:
        log.error(f"Batch format error: {e}")
        # Fallback: basic formatting
        lines = []
        for line in text_batch.strip().split('\n'):
            if line.strip():
                # Simple transform: "Show - Season X - Episode Y - [Date]" → "Show\nSeason X, Episode Y - [Date]"
                parts = line.split(' - Season ')
                if len(parts) == 2:
                    show = parts[0].strip()
                    rest = 'Season ' + parts[1].replace(' - Episode ', ', Episode ')
                    lines.append(f"• {show}\n{rest}")
                else:
                    lines.append(line)
        return '\n\n'.join(lines)

def rewrite(text):
    """Split long lists into batches, format each, combine"""
    if not text or not text.strip():
        return "🎬 New update!"
    
    # Parse lines
    lines = [l.strip() for l in text.strip().split('\n') if l.strip() and 'Season' in l]
    
    if not lines:
        return "🎬 New update!"
    
    # Group by show name
    shows = {}
    for line in lines:
        # Extract show name (everything before " - Season")
        show_name = line.split(' - Season ')[0].strip()
        if show_name not in shows:
            shows[show_name] = []
        # Transform: " - Season XX - Episode YY - [Date]" → "Season XX, Episode YY - [Date]"
        ep_part = line.split(' - Season ', 1)[1]
        ep_formatted = 'Season ' + ep_part.replace(' - Episode ', ', Episode ')
        shows[show_name].append(ep_formatted)
    
    # Build batches (max 8 shows per batch to stay under token limit)
    show_items = list(shows.items())
    batches = []
    current_batch = []
    current_count = 0
    
    for show_name, episodes in show_items:
        # Each show with many episodes counts as more
        weight = 1 + (len(episodes) // 5)
        if current_count + weight > 8 and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_count = 0
        current_batch.append((show_name, episodes))
        current_count += weight
    
    if current_batch:
        batches.append(current_batch)
    
    log.info(f"Split into {len(batches)} batches")
    
    # Format each batch
    formatted_parts = []
    for i, batch in enumerate(batches):
        # Build input text for this batch
        batch_text = "Today's Updates:\n\n"
        for show_name, episodes in batch:
            batch_text += f"{show_name} - " + " / ".join(episodes) + "\n"
        
        log.info(f"Formatting batch {i+1}/{len(batches)}...")
        formatted = format_batch(batch_text)
        formatted_parts.append(formatted)
    
    # Combine all parts
    full_output = "✨ Today\'s TV Show Updates ✨\n\n"
    
    # Renumber across all batches
    number = 1
    final_lines = []
    
    for part in formatted_parts:
        for line in part.split('\n'):
            # Detect show title lines (start with number or bullet)
            stripped = line.strip()
            if stripped and (stripped[0].isdigit() or stripped.startswith('•') or stripped.startswith('-')):
                # Extract show name after emoji or bullet
                if '.' in stripped and stripped[0].isdigit():
                    # Remove old number, add new
                    show_part = stripped.split('.', 1)[1].strip()
                elif stripped.startswith('•') or stripped.startswith('-'):
                    show_part = stripped[1:].strip()
                else:
                    show_part = stripped
                
                # Add emoji if missing
                if not any(ord(c) > 0x1F300 for c in show_part[:3]):
                    show_part = "📺 " + show_part
                
                final_lines.append(f"{number}. {show_part}")
                number += 1
            elif stripped.startswith('Season'):
                final_lines.append(stripped)
            elif stripped == '':
                final_lines.append('')
    
    full_output += '\n'.join(final_lines)
    full_output += "\n\nYou can download these episodes now from [https://t.me/t4tsaccbot]. Enjoy! 🎬🍿"
    
    return full_output

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

# ─── SEEN SET ───────────────────────────────────────────────────
seen_ids = load_seen()

# ─── COPY FUNCTION ────────────────────────────────────────────
async def copy_message(client, msg):
    global seen_ids
    
    if msg.id in seen_ids:
        log.info(f"Skipping #{msg.id} (already seen)")
        return
    
    text = msg.text or msg.raw_text or ""
    preview = text[:50].replace('\n', ' ') if text else "(no text)"
    log.info(f"New message #{msg.id}: {preview}")
    
    new_text = rewrite(text) if text else "🎬 New update!"
    
    try:
        # Split into Telegram chunks (4096 limit)
        MAX_LEN = 4000
        if len(new_text) > MAX_LEN:
            log.info(f"Output is {len(new_text)} chars, splitting...")
            chunks = []
            current = ""
            for line in new_text.split('\n'):
                if len(current) + len(line) + 1 > MAX_LEN:
                    chunks.append(current.strip())
                    current = line + '\n'
                else:
                    current += line + '\n'
            if current.strip():
                chunks.append(current.strip())
            
            # Send first chunk with media if present
            first = chunks[0]
            if msg.media:
                sent = await client.send_file(DEST, file=msg.media, caption=first)
            else:
                sent = await client.send_message(DEST, first)
            
            # Send remaining chunks
            for chunk in chunks[1:]:
                await client.send_message(DEST, chunk)
                await asyncio.sleep(2)
            
            log.info(f"✅ Sent in {len(chunks)} parts")
        else:
            if msg.media:
                sent = await client.send_file(DEST, file=msg.media, caption=new_text)
            else:
                sent = await client.send_message(DEST, new_text)
            log.info(f"✅ Copied to #{sent.id}")
        
        seen_ids.add(msg.id)
        save_seen(seen_ids)
        
    except Exception as e:
        log.error(f"❌ Failed: {e}")

# ─── TELEGRAM CLIENT ────────────────────────────────────────────
async def start_monitoring():
    log.info("=" * 50)
    log.info(f"Monitoring: @{SOURCE} -> @{DEST}")
    
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    
    @client.on(events.NewMessage(chats=SOURCE))
    async def handler(event):
        log.info(f"🔔 New message detected!")
        await copy_message(client, event.message)
    
    await client.start()
    log.info("✅ Monitoring started!")
    await client.run_until_disconnected()

# ─── FLASK ──────────────────────────────────────────────────────
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
    
    def run_monitor():
        asyncio.run(start_monitoring())
    
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    
    log.info(f"Web server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
