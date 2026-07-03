#!/usr/bin/env python3
"""Generate Telegram session string. Run ONCE on your computer."""

from telethon.sessions import StringSession
from telethon import TelegramClient

print("=" * 60)
print("  Telegram Session Generator")
print("=" * 60)

API_ID = int(input("Enter API_ID: ").strip())
API_HASH = input("Enter API_HASH: ").strip()

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        session = client.session.save()
        print("\n" + "=" * 60)
        print("  COPY THIS ENTIRE STRING (save it safely):")
        print("=" * 60)
        print(session)
        print("\n" + "=" * 60)
        print("  Add to Render as: SESSION_STRING")
        print("=" * 60)

import asyncio
asyncio.run(main())