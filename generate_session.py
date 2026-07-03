from telethon.sessions import StringSession
from telethon import TelegramClient

print("=" * 60)
print("Telegram Session Generator")
print("=" * 60)

API_ID = int(input("API_ID: ").strip())
API_HASH = input("API_HASH: ").strip()

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        s = client.session.save()
        print("\n" + "=" * 60)
        print("COPY THIS ENTIRE STRING (save it somewhere safe):")
        print("=" * 60)
        print(s)
        print("\n" + "=" * 60)
        print("Add to Render as: SESSION_STRING")
        print("=" * 60)

import asyncio
asyncio.run(main())
