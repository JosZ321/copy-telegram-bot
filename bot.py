import os
import json
import asyncio
import logging
import threading
import re
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

GEMINI_PROMPT = """You are an expert data-formatting assistant. Your task is to transform a raw, unformatted list of TV show updates into a highly clean, engaging, numbered, and emoji-enhanced list.

Follow these strict formatting rules instructions explicitly:

1. **Header:** Always start the response with exactly: "✨ Today's TV Show Updates ✨\n\n"

2. **Grouping & Condensing:** 
   - If a TV show appears multiple times with different episodes (e.g., bulk season drops), group them under ONE single numbered entry.
   - Do NOT repeat the show name or the number for multiple episodes of the same show.

3. **Numbering & Show Titles:** 
   - Format each unique show as: `[Number]. [Contextual Emoji] [Show Name]`
   - Dynamically select an emoji that fits the theme or title of the show (e.g., 🩺/🏥 for medical, 🕵️‍♂️/🔍 for crime/mystery, 🐉 for dragons, 🚀 for space, etc.).

4. **Episode Details:** 
   - On the line below the show title (or stacked lines if multiple episodes), format the season and episode exactly like this: `Season XX, Episode XX - [Date]`
   - Note: Change the original " - Season XX - Episode XX - " structure into "Season XX, Episode XX - " (using a comma instead of a dash between Season and Episode).

5. **Spacing & Line Breaks:**
   - Show Title to Episode: Do NOT insert a blank line between the show's title line and its first episode detail line.
   - Multi-Episode Stacking: When grouping multiple episodes under a single show, stack the episode detail lines directly underneath each other with NO blank lines between them.
   - Between Separate Entries: Insert exactly one single blank line between the last episode line of the current numbered entry and the title line of the next numbered entry.
   - Header & Footer Margins: Ensure there is exactly one single blank line separating the header from entry #1, and exactly one single blank line separating the final entry from the footer message.

6. **Footer:** Always end the output with exactly: "\nYou can download these episodes now from [https://t.me/t4tsaccbot]. Enjoy! 🎬🍿"

Here is an example input and your expected output:

---

INPUT:

Today's Updates:

Human Vapor - Season 01 - Episode 02 - [Jul 03, 2026]
Human Vapor - Season 01 - Episode 01 - [Jul 03, 2026]

OUTPUT:

✨ Today's TV Show Updates ✨

1. 💨 Human Vapor
Season 01, Episode 02 - [Jul 03, 2026]
Season 01, Episode 01 - [Jul 03, 2026]

You can download these episodes now from [https://t.me/t4tsaccbot]. Enjoy! 🎬🍿

---

Now format this input:

{text}"""

def format_with_gemini(text):
    """Send text to Gemini, get formatted output."""
    try:
        r = requests.post(GEMINI_URL, json={
            "contents": [{"parts": [{"text": GEMINI_PROMPT.format(text=text)}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
        }, timeout=30)
        r.raise_for_status()
        
        data = r.json()
        # Debug: log the structure
        log.info(f"Gemini response keys: {list(data.keys())}")
        
        # Handle different response structures
        candidates = data.get('candidates', [])
        if not candidates:
            log.error("No candidates in Gemini response")
            return None
        
        content = candidates[0].get('content', {})
        if isinstance(content, dict):
            parts = content.get('parts', [])
            if parts and isinstance(parts[0], dict):
                out = parts[0].get('text', '').strip()
            else:
                out = str(parts[0]).strip() if parts else ''
        else:
            out = str(content).strip()
        
        out = out.replace('```', '').strip()
        return out
        
    except Exception as e:
        log.error(f"Gemini error: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None

# ─── PARSER ─────────────────────────────────────────────────────
def parse_episodes(text):
    """Parse raw text into structured episodes."""
    episodes = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or 'Season' not in line or 'Episode' not in line:
            continue
        match = re.search(r'(.*?)\s+-\s+Season\s+(\d+)\s+-\s+Episode\s+(\d+)\s+-\s+(\[.*?\])', line)
        if match:
            episodes.append({
                'show': match.group(1).strip(),
                'season': match.group(2).strip(),
                'episode': match.group(3).strip(),
                'date': match.group(4).strip()
            })
    return episodes

# ─── SPLIT & FORMAT ─────────────────────────────────────────────
def rewrite(text):
    """Split into batches, format each with Gemini, combine."""
    if not text or not text.strip():
        return "🎬 New update!"
    
    episodes = parse_episodes(text)
    if not episodes:
        return "🎬 New update!"
    
    # Group by show
    shows = {}
    show_order = []
    for ep in episodes:
        show = ep['show']
        if show not in shows:
            shows[show] = []
            show_order.append(show)
        shows[show].append(ep)
    
    # Sort episodes within each show
    for show in shows:
        shows[show].sort(key=lambda x: (int(x['season']), int(x['episode'])))
    
    # Split shows into batches of max 8 shows (to stay under token limit)
    batches = []
    current_batch = []
    current_weight = 0
    
    for show in show_order:
        # Weight = 1 + episodes//5 (more episodes = more tokens)
        weight = 1 + (len(shows[show]) // 5)
        if current_weight + weight > 8 and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_weight = 0
        current_batch.append(show)
        current_weight += weight
    
    if current_batch:
        batches.append(current_batch)
    
    log.info(f"Split into {len(batches)} batches for Gemini")
    
    # Format each batch
    formatted_parts = []
    for i, batch in enumerate(batches):
        # Build input text for this batch
        batch_lines = ["Today's Updates:", ""]
        for show in batch:
            for ep in shows[show]:
                batch_lines.append(f"{show} - Season {ep['season']} - Episode {ep['episode']} - {ep['date']}")
        
        batch_text = '\n'.join(batch_lines)
        log.info(f"Formatting batch {i+1}/{len(batches)} ({len(batch)} shows)...")
        
        result = format_with_gemini(batch_text)
        if result:
            # Strip header/footer from middle batches
            lines = result.split('\n')
            # Remove header
            while lines and ('✨' in lines[0] or lines[0].strip() == ''):
                lines.pop(0)
            # Remove footer
            while lines and ('download' in lines[-1].lower() or 'enjoy' in lines[-1].lower() or lines[-1].strip() == ''):
                lines.pop()
            
            formatted_parts.append('\n'.join(lines))
        else:
            # Fallback: basic format
            fallback = []
            for show in batch:
                fallback.append(f"📺 {show}")
                for ep in shows[show]:
                    fallback.append(f"Season {ep['season']}, Episode {ep['episode']} - {ep['date']}")
                fallback.append("")
            formatted_parts.append('\n'.join(fallback))
    
    # Combine all parts with proper numbering
    final_lines = ["✨ Today's TV Show Updates ✨", ""]
    
    number = 1
    for part in formatted_parts:
        for line in part.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Detect show title line (starts with number or has emoji)
            match = re.match(r'(\d+)\.\s+(\S+)\s+(.*)', line)
            if match:
                # Replace old number with sequential number
                emoji = match.group(2)
                name = match.group(3)
                final_lines.append(f"{number}. {emoji} {name}")
                number += 1
            elif line.startswith('Season'):
                final_lines.append(line)
            elif any(ord(c) > 0x1F300 for c in line[:5]):
                # Line starts with emoji but no number
                final_lines.append(f"{number}. {line}")
                number += 1
        
        final_lines.append("")  # blank line between batches
    
    # Clean up
    while final_lines and final_lines[-1] == "":
        final_lines.pop()
    
    final_lines.append("")
    final_lines.append("You can download these episodes now from [https://t.me/t4tsaccbot]. Enjoy! 🎬🍿")
    
    return '\n'.join(final_lines)

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
