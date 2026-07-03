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

# ─── SMART EMOJI FINDER ─────────────────────────────────────────
def get_smart_emoji(show_name):
    """Find best emoji for a show name."""
    sl = show_name.lower()
    
    # Exact matches first (most specific)
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
        'zatima': '💖',
        'the mcbee dynasty - real american cowboys': '🤠',
        'sugarcreek amish mysteries': '🌾',
        'staged - deadly deception': '🎭',
        'pardon the intrusion i am home': '🏠',
        'morfeusz': '💊',
        'maximum pleasure guaranteed': '🔞',
        'marriagetoxin': '💍',
        'doctor on the edge': '🩺',
        'bust up': '💥',
        'the killings at parrish station': '🔪',
        'the warrior princess and the barbaric king': '⚔️',
        'welcome to wrexham': '⚽',
        'avatar - the last airbender': '🌊',
    }
    
    for name, emoji in exact.items():
        if name in sl:
            return emoji
    
    # Keyword matching (broader)
    keywords = [
        (['dragon', 'fantasy', 'magic', 'witch', 'demon', 'vampire', 'werewolf', 'rava'], '🐉'),
        (['medical', 'hospital', 'doctor', 'nurse', 'patient', 'surgeon', 'emergency', 'medic', 'health', 'clinic'], '🩺'),
        (['crime', 'detective', 'murder', 'police', 'fbi', 'cia', 'investigation', 'serial killer', 'mystery', 'killing', 'kill', 'dead', 'death', 'murdered', 'parrish'], '🔍'),
        (['space', 'star', 'alien', 'mars', 'planet', 'galaxy', 'cosmos', 'astronaut', 'jupiter'], '🚀'),
        (['war', 'battle', 'soldier', 'army', 'navy', 'marine', 'combat', 'warrior', 'king', 'queen', 'throne', 'dynasty', 'princess', 'barbaric'], '⚔️'),
        (['comedy', 'funny', 'laugh', 'sitcom', 'humor', 'comic'], '😂'),
        (['horror', 'scary', 'ghost', 'zombie', 'haunted', 'evil', 'devil', 'fear', 'terror'], '👻'),
        (['ice', 'snow', 'cold', 'winter', 'frozen', 'arctic', 'antarctica'], '❄️'),
        (['doom', 'dark', 'death', 'apocalypse', 'end of world', 'dystopia'], '💀'),
        (['agent', 'spy', 'secret', 'mission', 'intelligence', 'covert', 'cia', 'fbi', 'ninja'], '🕵️'),
        (['fight', 'martial', 'karate', 'kung', 'boxing', 'mma', 'ufc', 'fist', 'punch', 'star', 'hokuto'], '👊'),
        (['ranch', 'cowboy', 'west', 'horse', 'frontier', 'outlaw', 'cowboys', 'mcbee'], '🤠'),
        (['gate', 'portal', 'dimension', 'parallel', 'time travel', 'beyond'], '🚪'),
        (['music', 'song', 'band', 'concert', 'singer', 'album', 'rap', 'hip hop', 'note', 'row'], '🎵'),
        (['life', 'happiness', 'pursuit', 'reincarnation', 'afterlife', 'rebirth', 'living'], '🌟'),
        (['earth', 'world', 'globe', 'nature', 'environment', 'climate', 'planet', 'snowball'], '🌍'),
        (['proud', 'pride', 'honor', 'glory', 'champion', 'victory', 'win'], '🏆'),
        (['city', 'urban', 'metro', 'downtown', 'street', 'gang', 'chi'], '🏙️'),
        (['castle', 'fortress', 'rampart', 'kingdom', 'empire', 'medieval'], '🏰'),
        (['ninja', 'samurai', 'japan', 'shogun', 'ronin', 'dojo'], '🥷'),
        (['cat', 'kitten', 'feline', 'meow', 'purr'], '🐱'),
        (['dog', 'puppy', 'canine', 'woof', 'bark'], '🐶'),
        (['family', 'parent', 'child', 'kids', 'mother', 'father', 'dynasty', 'home', 'intrusion'], '👨‍👩‍👧‍👦'),
        (['food', 'cook', 'chef', 'restaurant', 'kitchen', 'recipe', 'sugar', 'sugarcreek', 'amish'], '🍳'),
        (['sport', 'football', 'soccer', 'basketball', 'baseball', 'team', 'wrexham'], '⚽'),
        (['school', 'student', 'teacher', 'class', 'university', 'college'], '🎓'),
        (['money', 'rich', 'wealth', 'billionaire', 'business', 'corporate', 'maximum', 'pleasure'], '💰'),
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
        (['amish', 'country', 'rural', 'farm', 'barn'], '🌾'),
        (['home', 'house', 'intrusion', 'family', 'domestic'], '🏠'),
        (['stage', 'act', 'theater', 'play', 'performance', 'deception'], '🎭'),
        (['marriage', 'wedding', 'bride', 'groom', 'divorce', 'toxin'], '💍'),
        (['doctor', 'medic', 'hospital', 'clinic', 'surgery', 'edge'], '🩺'),
        (['bust', 'explosion', 'break', 'destroy', 'crash'], '💥'),
        (['pleasure', 'desire', 'passion', 'romance', 'adult'], '🔞'),
        (['edge', 'cliff', 'danger', 'risk', 'extreme'], '⚠️'),
        (['parrish', 'station', 'train', 'railway', 'subway'], '🚉'),
        (['vapor', 'steam', 'mist', 'fog'], '💨'),
        (['doom', 'doomies', 'dark', 'evil'], '💀'),
        (['snoopy', 'peanuts', 'beagle', 'dog'], '🏕️'),
        (['wrexham', 'football', 'soccer', 'sport'], '⚽'),
        (['avatar', 'bender', 'element', 'air', 'water', 'fire', 'earth'], '🌊'),
        (['bear', 'restaurant', 'chef', 'cook', 'kitchen'], '🐻'),
        (['island', 'love', 'dating', 'romance', 'paradise'], '💕'),
        (['kanan', 'power', 'book', 'drug', 'cartel', 'gang'], '👑'),
        (['hokuto', 'ken', 'fist', 'north', 'star'], '👊'),
        (['jones', 'jupiter', 'space', 'planet'], '🪐'),
        (['minds', 'brain', 'smart', 'intelligent', 'genius'], '🧠'),
        (['fear', 'shark', 'ocean', 'sea'], '🦈'),
        (['reincarnation', 'petal', 'flower', 'bloom', 'rebirth'], '🌸'),
        (['rampart', 'ice', 'wall', 'fortress', 'castle'], '🏰'),
        (['proud', 'pride', 'honor', 'glory'], '🏆'),
        (['dutton', 'ranch', 'cowboy', 'west', 'yellowstone'], '🤠'),
        (['kim', 'agent', 'spy', 'reactivate', 'mission'], '🕵️'),
        (['larry', 'life', 'unhappiness', 'pursuit', 'happiness'], '😔'),
        (['chain', 'smoke', 'cat', 'feline'], '🐱'),
        (['tattas', 'dutch', 'netherlands', 'holland'], '🇳🇱'),
        (['silo', 'underground', 'bunker', 'post-apocalyptic'], '🌾'),
        (['zatima', 'zeke', 'fatima', 'love', 'relationship'], '💖'),
        (['sugarcreek', 'amish', 'mystery', 'murder'], '🌾'),
        (['staged', 'deception', 'fake', 'lie', 'trick'], '🎭'),
        (['pardon', 'intrusion', 'home', 'house', 'family'], '🏠'),
        (['morfeusz', 'dream', 'sleep', 'pill', 'drug'], '💊'),
        (['maximum', 'pleasure', 'guarantee', 'adult'], '🔞'),
        (['marriagetoxin', 'marriage', 'wedding', 'poison'], '💍'),
        (['doctor', 'edge', 'hospital', 'medic'], '🩺'),
        (['bust', 'up', 'explosion', 'break'], '💥'),
        (['killings', 'parrish', 'station', 'murder'], '🔪'),
        (['warrior', 'princess', 'barbaric', 'king', 'fantasy'], '⚔️'),
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

# ─── FORMATTER ──────────────────────────────────────────────────
def rewrite(text):
    """Format TV show list using pure Python. Reliable, no truncation."""
    if not text or not text.strip():
        return "🎬 New update!"
    
    episodes = parse_episodes(text)
    if not episodes:
        return "🎬 New update!"
    
    # Group by show (preserve first appearance order)
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
    
    # Build output
    lines = ["✨ Today\'s TV Show Updates ✨", ""]
    
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

# ─── TELEGRAM SPLITTER ─────────────────────────────────────────
def split_for_telegram(text, max_len=4000):
    """Split text into chunks that fit Telegram's limit.
    Never split in the middle of a show entry."""
    lines = text.split('\n')
    
    # Extract header
    header_lines = []
    while lines and ('✨' in lines[0] or lines[0].strip() == ''):
        header_lines.append(lines.pop(0))
    
    # Extract footer
    footer_lines = []
    while lines and lines[-1].strip() != '':
        footer_lines.insert(0, lines.pop())
    
    # Group into show entries
    entries = []
    current_entry = []
    for line in lines:
        if line.strip() == '':
            if current_entry:
                entries.append(current_entry)
                current_entry = []
        else:
            current_entry.append(line)
    if current_entry:
        entries.append(current_entry)
    
    # Build chunks
    chunks = []
    current = list(header_lines)
    
    for entry in entries:
        entry_text = '\n'.join(entry) + '\n\n'
        current_text = '\n'.join(current)
        
        if len(current_text) + len(entry_text) > max_len and current:
            # Finish current chunk
            chunks.append('\n'.join(current).strip())
            # Start new chunk
            current = ["✨ Today\'s TV Show Updates ✨ (continued)", ""] + entry
        else:
            current.extend(entry)
            current.append('')
    
    # Add footer to last chunk
    if current:
        current.extend(footer_lines)
        chunks.append('\n'.join(current).strip())
    
    return chunks

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
        # Use smart splitter
        chunks = split_for_telegram(new_text, max_len=4000)
        
        if len(chunks) > 1:
            log.info(f"Split into {len(chunks)} Telegram messages")
        
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
        
        log.info(f"✅ Sent {len(chunks)} message(s)")
        
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
