import os
import json
import asyncio
import logging
import threading
import re
import time
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

# ─── GEMINI SETUP ───────────────────────────────────────────────
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite"]

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
    """Try multiple Gemini models, return formatted text or None."""
    payload = {
        "contents": [{"parts": [{"text": GEMINI_PROMPT.format(text=text)}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
    }
    
    for model in GEMINI_MODELS:
        url = GEMINI_URL_TEMPLATE.format(model=model, key=GEMINI_KEY)
        try:
            log.info(f"Trying {model}...")
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status()
            
            data = r.json()
            candidates = data.get('candidates', [])
            if not candidates:
                continue
            
            content = candidates[0].get('content', {})
            parts = content.get('parts', []) if isinstance(content, dict) else []
            
            if parts and isinstance(parts[0], dict):
                out = parts[0].get('text', '').strip()
            else:
                out = str(parts[0]).strip() if parts else ''
            
            if out:
                out = out.replace('```', '').strip()
                log.info(f"✅ {model} worked")
                return out
                
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 503:
                log.warning(f"{model} unavailable (503)")
                continue
            if status == 429:
                log.warning(f"{model} rate limited, waiting...")
                time.sleep(5)
                continue
            log.error(f"{model} HTTP {status}")
            return None
        except Exception as e:
            log.error(f"{model} error: {e}")
            continue
    
    log.error("All Gemini models failed")
    return None

# ─── SMART EMOJI FINDER ─────────────────────────────────────────
def get_smart_emoji(show_name):
    """Find best emoji for a show name."""
    sl = show_name.lower()
    
    # Exact matches first
    exact = {
        'avatar - the last airbender': '🌊',
        'the bear': '🐻',
        'love island': '💕',
        'love island us': '💕',
        'welcome to wrexham': '⚽',
        'camp snoopy': '🏕️',
        'ninja to gokudou': '🥷',
        'power book iii - raising kanan': '👑',
        'fist of the north star - hokuto no ken': '👊',
        'star city': '⭐',
        'jupiter jones': '🪐',
        'beyond the gates': '🚪',
        'brilliant minds': '🧠',
        'cape fear': '🦈',
        'the chi': '🏙️',
        'petals of reincarnation': '🌸',
        'human vapor': '💨',
        'the doomies': '💀',
        'ravalear': '🐉',
        'notes from the last row': '🎵',
        'snowball earth': '❄️',
        'the ramparts of ice': '🏰',
        'proud': '🏆',
        'dutton ranch': '🤠',
        'agent kim reactivated': '🕵️',
        'life larry and the pursuit of unhappiness': '😔',
        'chainsmoker cat': '🐱',
        'de tattas - de serie': '🇳🇱',
        'sugar': '🍬',
        'silo': '🌾',
    }
    
    for name, emoji in exact.items():
        if name in sl:
            return emoji
    
    # Keyword matching
    keywords = [
        (['dragon', 'fantasy', 'magic', 'witch', 'demon', 'vampire', 'werewolf'], '🐉'),
        (['medical', 'hospital', 'doctor', 'nurse', 'patient', 'surgeon', 'emergency'], '🩺'),
        (['crime', 'detective', 'murder', 'police', 'fbi', 'cia', 'investigation', 'serial killer'], '🔍'),
        (['space', 'star', 'alien', 'mars', 'planet', 'galaxy', 'cosmos', 'astronaut'], '🚀'),
        (['war', 'battle', 'soldier', 'army', 'navy', 'marine', 'combat', 'warrior', 'king', 'queen', 'throne'], '⚔️'),
        (['comedy', 'funny', 'laugh', 'sitcom', 'humor'], '😂'),
        (['horror', 'scary', 'ghost', 'zombie', 'haunted', 'evil', 'devil'], '👻'),
        (['ice', 'snow', 'cold', 'winter', 'frozen', 'arctic', 'antarctica'], '❄️'),
        (['doom', 'dark', 'death', 'apocalypse', 'end of world', 'dystopia'], '💀'),
        (['agent', 'spy', 'secret', 'mission', 'intelligence', 'covert'], '🕵️'),
        (['fight', 'martial', 'karate', 'kung', 'boxing', 'mma', 'ufc'], '👊'),
        (['ranch', 'cowboy', 'west', 'horse', 'frontier', 'outlaw'], '🤠'),
        (['gate', 'portal', 'dimension', 'parallel', 'time travel'], '🚪'),
        (['music', 'song', 'band', 'concert', 'singer', 'album', 'rap', 'hip hop'], '🎵'),
        (['life', 'happiness', 'pursuit', 'reincarnation', 'afterlife', 'rebirth'], '🌟'),
        (['earth', 'world', 'globe', 'nature', 'environment', 'climate'], '🌍'),
        (['proud', 'pride', 'honor', 'glory', 'champion', 'victory'], '🏆'),
        (['city', 'urban', 'metro', 'downtown', 'street', 'gang'], '🏙️'),
        (['castle', 'fortress', 'rampart', 'kingdom', 'empire', 'medieval'], '🏰'),
        (['ninja', 'samurai', 'japan', 'shogun', 'ronin', 'dojo'], '🥷'),
        (['cat', 'kitten', 'feline', 'meow', 'purr'], '🐱'),
        (['dog', 'puppy', 'canine', 'woof', 'bark'], '🐶'),
        (['family', 'parent', 'child', 'kids', 'mother', 'father'], '👨‍👩‍👧‍👦'),
        (['food', 'cook', 'chef', 'restaurant', 'kitchen', 'recipe'], '🍳'),
        (['sport', 'football', 'soccer', 'basketball', 'baseball', 'team'], '⚽'),
        (['school', 'student', 'teacher', 'class', 'university', 'college'], '🎓'),
        (['money', 'rich', 'wealth', 'billionaire', 'business', 'corporate'], '💰'),
        (['car', 'drive', 'race', 'motor', 'speed', 'highway'], '🏎️'),
        (['plane', 'fly', 'airport', 'pilot', 'flight', 'travel'], '✈️'),
        (['boat', 'ship', 'sea', 'ocean', 'sail', 'cruise', 'navy'], '⚓'),
        (['robot', 'ai', 'cyborg', 'android', 'machine', 'future', 'tech'], '🤖'),
        (['superhero', 'hero', 'villain', 'comic', 'marvel', 'dc', 'powers'], '🦸'),
        (['prison', 'jail', 'convict', 'escape', 'heist', 'robbery'], '⛓️'),
        (['court', 'lawyer', 'judge', 'trial', 'justice', 'legal'], '⚖️'),
        (['politics', 'president', 'government', 'election', 'white house'], '🏛️'),
        (['religion', 'god', 'church', 'faith', 'bible', 'priest'], '⛪'),
        (['alien', 'ufo', 'extraterrestrial', 'mars', 'area 51'], '👽'),
        (['dinosaur', 'jurassic', 'prehistoric', 'trex', 'raptor'], '🦖'),
        (['pirate', 'treasure', 'caribbean', 'captain', 'ship'], '☠️'),
        (['viking', 'norse', 'odin', 'thor', 'valhalla', 'ragnarok'], '🪓'),
        (['zombie', 'undead', 'infection', 'virus', 'outbreak'], '🧟'),
        (['angel', 'heaven', 'guardian', 'wings', 'divine'], '👼'),
        (['devil', 'hell', 'demon', 'satan', 'possession'], '😈'),
        (['circus', 'clown', 'carnival', 'freak', 'performance'], '🎪'),
        (['circus', 'clown', 'carnival', 'freak', 'performance'], '🎪'),
    ]
    
    for words, emoji in keywords:
        if any(w in sl for w in words):
            return emoji
    
    return '📺'

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

# ─── PYTHON FALLBACK FORMATTER ─────────────────────────────────
def python_format(shows, show_order):
    """Format shows using Python (no Gemini needed). Smart emojis included."""
    lines = ["✨ Today's TV Show Updates ✨", ""]
    
    for i, show in enumerate(show_order, 1):
        emoji = get_smart_emoji(show)
        lines.append(f"{i}. {emoji} {show}")
        
        for ep in shows[show]:
            lines.append(f"Season {ep['season']}, Episode {ep['episode']} - {ep['date']}")
        
        lines.append("")
    
    # Remove trailing blank
    if lines and lines[-1] == "":
        lines.pop()
    
    lines.append("")
    lines.append("You can download these episodes now from [https://t.me/t4tsaccbot]. Enjoy! 🎬🍿")
    
    return '\n'.join(lines)

# ─── MAIN REWRITE ───────────────────────────────────────────────
def rewrite(text):
    """Format TV show list. Try Gemini first, fallback to Python."""
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
    
    # Try Gemini first (for best emojis and formatting)
    # Only use Gemini for small lists (under 15 shows) to avoid token limits
    if len(show_order) <= 15:
        # Build full input
        input_lines = ["Today's Updates:", ""]
        for show in show_order:
            for ep in shows[show]:
                input_lines.append(f"{show} - Season {ep['season']} - Episode {ep['episode']} - {ep['date']}")
        
        gemini_result = format_with_gemini('\n'.join(input_lines))
        
        if gemini_result:
            log.info("✅ Used Gemini formatting")
            return gemini_result
    
    # Fallback: Python formatting with smart emojis
    log.info("Using Python fallback with smart emojis")
    return python_format(shows, show_order)

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
