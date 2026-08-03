#!/usr/bin/env python3
"""Telegram Auth Helper - authenticate and save session for MCP server"""
import sys
import os
import json
import asyncio
from telethon import TelegramClient


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"ERROR: set {name} (e.g. in ~/.opsora_env) before running")
    return value


API_ID = int(_require_env("TELEGRAM_API_ID"))
API_HASH = _require_env("TELEGRAM_API_HASH")
PHONE = _require_env("TELEGRAM_PHONE")
SESSION_PATH = "/root/.telegram-mcp/opsora"
HASH_FILE = "/tmp/tg_phone_code_hash.json"

async def send_code():
    os.makedirs("/root/.telegram-mcp", exist_ok=True)
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized as: {me.first_name} (@{me.username})")
        await client.disconnect()
        return

    result = await client.send_code_request(PHONE)
    # Save the phone_code_hash
    with open(HASH_FILE, "w") as f:
        json.dump({"phone_code_hash": result.phone_code_hash}, f)
    print("CODE_SENT")
    await client.disconnect()

async def verify_code(code, password=None):
    # Load the phone_code_hash
    with open(HASH_FILE) as f:
        data = json.load(f)
    phone_code_hash = data["phone_code_hash"]

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized as: {me.first_name} (@{me.username})")
        await client.disconnect()
        return

    try:
        await client.sign_in(PHONE, code, phone_code_hash=phone_code_hash)
    except Exception as e:
        err = str(e)
        if "SessionPasswordNeeded" in type(e).__name__ or "Two-steps" in err:
            if password:
                await client.sign_in(password=password)
            else:
                print("NEED_2FA")
                await client.disconnect()
                return
        else:
            print(f"ERROR: {e}")
            await client.disconnect()
            return

    me = await client.get_me()
    print(f"SUCCESS: {me.first_name} (@{me.username})")
    os.remove(HASH_FILE)
    await client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        asyncio.run(send_code())
        print(f"\nRun: python3 {sys.argv[0]} YOUR_CODE [2FA_PASSWORD]")
    else:
        code = sys.argv[1]
        pw = sys.argv[2] if len(sys.argv) > 2 else None
        asyncio.run(verify_code(code, pw))
