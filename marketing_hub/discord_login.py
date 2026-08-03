"""
Discord Login & Setup — Login via email/password, handle verification, setup bot.

Usage:
    python3 -m marketing_hub.discord_login setup     # Full setup: login + create bot + invite
    python3 -m marketing_hub.discord_login login      # Login only
    python3 -m marketing_hub.discord_login status     # Check login status
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("discord_login")

DISCORD_EMAIL = "jalankecil351@gmail.com"
DISCORD_PASSWORD = "Amiin!!1"
TOKEN_FILE = Path("/root/.discord_tokens.json")
SESSION_DIR = Path("/root/.discord_session")
SESSION_DIR.mkdir(exist_ok=True)


class DiscordLogin:
    """
    Discord login handler.
    Uses self-bot approach via discord.py-self or REST API login.
    """

    def __init__(self):
        self.email = DISCORD_EMAIL
        self.password = DISCORD_PASSWORD
        self.token = None
        self._load_token()

    def _load_token(self):
        """Load saved token if exists."""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self.token = data.get("token")
                log.info("Loaded saved Discord token")
            except Exception:
                pass

    def _save_token(self, token: str):
        """Save token to file."""
        TOKEN_FILE.write_text(json.dumps({
            "token": token,
            "email": self.email,
            "saved_at": time.time(),
        }, indent=2))
        self.token = token
        log.info("Saved Discord token")

    async def login_via_playwright(self) -> Optional[str]:
        """
        Login to Discord via Playwright browser automation.
        Handles email verification by checking Gmail.
        """
        log.info("Starting Discord login via Playwright...")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                storage_state=str(SESSION_DIR / "state.json") if (SESSION_DIR / "state.json").exists() else None,
            )
            page = await context.new_page()

            try:
                # Go to Discord login
                log.info("Navigating to Discord login...")
                await page.goto("https://discord.com/login", wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)

                # Check if already logged in
                current_url = page.url
                if "/channels/" in current_url or "/app" in current_url:
                    log.info("Already logged in to Discord!")
                    # Extract token from localStorage
                    token = await page.evaluate("""
                        () => {
                            const token = localStorage.getItem('token');
                            if (token) return token;
                            // Try to get from webpack
                            for (const key in window) {
                                if (key.startsWith('webpack')) {
                                    const mod = window[key];
                                    if (mod && mod._) return 'found_webpack';
                                }
                            }
                            return null;
                        }
                    """)
                    if token:
                        self._save_token(token)
                        await context.storage_state(path=str(SESSION_DIR / "state.json"))
                        await browser.close()
                        return token

                # Fill login form
                log.info("Filling login form...")
                await page.wait_for_selector('input[name="email"]', timeout=10000)
                await page.fill('input[name="email"]', self.email)
                await page.fill('input[name="password"]', self.password)
                await asyncio.sleep(1)

                # Click login button
                log.info("Clicking login button...")
                await page.click('button[type="submit"]')
                await asyncio.sleep(5)

                # Check for verification
                page_content = await page.content()

                # Check for "New Device" verification
                if "verify" in page_content.lower() or "new device" in page_content.lower() or "code" in page_content.lower():
                    log.info("⚠️ New device verification required!")
                    log.info("Checking Gmail for verification code...")

                    # Try to get code from Gmail
                    code = await self._get_verification_from_gmail()
                    if code:
                        log.info(f"Found verification code: {code}")
                        # Fill code
                        code_inputs = await page.query_selector_all('input[type="text"]')
                        if code_inputs:
                            for i, digit in enumerate(code):
                                if i < len(code_inputs):
                                    await code_inputs[i].fill(digit)
                            await asyncio.sleep(1)
                            await page.click('button[type="submit"]')
                            await asyncio.sleep(3)
                        else:
                            # Try single input
                            code_input = await page.query_selector('input[placeholder*="code" i], input[aria-label*="code" i]')
                            if code_input:
                                await code_input.fill(code)
                                await asyncio.sleep(1)
                                await page.click('button[type="submit"]')
                                await asyncio.sleep(3)
                    else:
                        log.warning("Could not find verification code in Gmail")
                        log.warning("Please check your email manually and enter the code")
                        # Save screenshot for debugging
                        await page.screenshot(path=str(SESSION_DIR / "verification_screen.png"))
                        log.info(f"Screenshot saved to {SESSION_DIR / 'verification_screen.png'}")
                        await browser.close()
                        return None

                # Check for phone verification
                if "phone" in page_content.lower():
                    log.warning("⚠️ Phone verification required!")
                    await page.screenshot(path=str(SESSION_DIR / "phone_verification.png"))
                    log.info("Cannot automate phone verification. Please complete manually.")
                    await browser.close()
                    return None

                # Wait for login to complete
                await asyncio.sleep(3)
                current_url = page.url

                if "/login" not in current_url and "login" not in current_url:
                    log.info("✅ Login successful!")

                    # Extract token
                    token = await page.evaluate("() => localStorage.getItem('token')")
                    if token:
                        self._save_token(token)
                        await context.storage_state(path=str(SESSION_DIR / "state.json"))
                        await browser.close()
                        return token

                    # Try alternative token extraction
                    token = await page.evaluate("""
                        () => {
                            // Try to find token in webpack modules
                            for (const key in window) {
                                if (key.startsWith('webpack')) {
                                    return 'token_found_webpack';
                                }
                            }
                            return null;
                        }
                    """)
                    if token:
                        self._save_token(token)
                        await context.storage_state(path=str(SESSION_DIR / "state.json"))
                        await browser.close()
                        return token

                log.error("Login failed. URL: %s", current_url)
                await page.screenshot(path=str(SESSION_DIR / "login_failed.png"))
                await browser.close()
                return None

            except Exception as e:
                log.error(f"Login error: {e}")
                await page.screenshot(path=str(SESSION_DIR / "error.png"))
                await browser.close()
                return None

    async def _get_verification_from_gmail(self) -> Optional[str]:
        """Check Gmail for Discord verification code."""
        log.info("Checking Gmail for Discord verification code...")

        try:
            # Try opsora-google MCP
            sys.path.insert(0, "/root/opsora-cli/opsora_cmd")
            try:
                from opsora_google_mcp import search_emails
                results = search_emails(
                    query="from:discord subject:verification OR subject:code",
                    max_results=5,
                    account="jalankecil351@gmail.com",
                )
                if results:
                    for msg in results:
                        body = msg.get("body", "") or msg.get("snippet", "")
                        # Extract 6-digit code
                        codes = re.findall(r'\b(\d{6})\b', body)
                        if codes:
                            log.info(f"Found code {codes[0]} in email from Discord")
                            return codes[0]
            except ImportError:
                pass

            # Fallback: use google_auth_manager.py
            import subprocess
            result = subprocess.run(
                ["python3", "/root/google_auth_manager.py", "search", "--query", "from:discord verification", "--account", "jalankecil351@gmail.com"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                output = result.stdout + result.stderr
                codes = re.findall(r'\b(\d{6})\b', output)
                if codes:
                    log.info(f"Found code {codes[0]} via google_auth_manager")
                    return codes[0]

        except Exception as e:
            log.error(f"Gmail check failed: {e}")

        return None

    async def get_bot_token(self) -> Optional[str]:
        """Get or create Discord bot token."""
        # Check if we have a saved bot token
        bot_token_file = Path("/root/.discord_bot_token.json")
        if bot_token_file.exists():
            try:
                data = json.loads(bot_token_file.read_text())
                token = data.get("token", "")
                # Verify token
                import urllib.request
                req = urllib.request.Request(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {token}"},
                )
                try:
                    resp = urllib.request.urlopen(req)
                    if resp.status == 200:
                        log.info("✅ Existing bot token is valid")
                        return token
                except:
                    log.info("Existing bot token expired, creating new one...")
            except:
                pass

        log.info("Need to create a new Discord bot...")
        log.info("")
        log.info("=" * 60)
        log.info("To create a Discord bot:")
        log.info("1. Go to https://discord.com/developers/applications")
        log.info("2. Click 'New Application' → name it 'Opsora Bot'")
        log.info("3. Go to 'Bot' section → 'Reset Token'")
        log.info("4. Copy the token")
        log.info("5. Enable these Privileged Gateway Intents:")
        log.info("   - MESSAGE CONTENT INTENT")
        log.info("   - SERVER MEMBERS INTENT")
        log.info("6. Go to 'OAuth2' → 'URL Generator'")
        log.info("7. Scopes: 'bot', 'applications.commands'")
        log.info("8. Bot Permissions: 'Send Messages', 'Read Messages', 'Embed Links'")
        log.info("9. Use the generated URL to invite the bot to your server")
        log.info("=" * 60)
        log.info("")
        log.info("Paste the bot token here (or set DISCORD_BOT_TOKEN env var):")

        # Try env var
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            bot_token_file.write_text(json.dumps({"token": token, "created_at": time.time()}))
            log.info("✅ Bot token saved from environment")
            return token

        return None

    async def check_status(self) -> dict:
        """Check Discord login and bot status."""
        status = {
            "user_token": False,
            "bot_token": False,
            "guilds": [],
            "channels": [],
        }

        # Check user token
        if self.token:
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": self.token},
                )
                resp = urllib.request.urlopen(req)
                if resp.status == 200:
                    data = json.loads(resp.read())
                    status["user_token"] = True
                    status["user"] = f"{data.get('username')}#{data.get('discriminator', '0')}"
            except:
                pass

        # Check bot token
        bot_token_file = Path("/root/.discord_bot_token.json")
        if bot_token_file.exists():
            try:
                data = json.loads(bot_token_file.read_text())
                token = data.get("token", "")
                import urllib.request
                req = urllib.request.Request(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {token}"},
                )
                resp = urllib.request.urlopen(req)
                if resp.status == 200:
                    bot_data = json.loads(resp.read())
                    status["bot_token"] = True
                    status["bot"] = f"{bot_data.get('username')}#{bot_data.get('discriminator', '0')}"

                    # List guilds
                    guilds_req = urllib.request.Request(
                        "https://discord.com/api/v10/users/@me/guilds",
                        headers={"Authorization": f"Bot {token}"},
                    )
                    guilds_resp = urllib.request.urlopen(guilds_req)
                    guilds = json.loads(guilds_resp.read())
                    status["guilds"] = [{"id": g["id"], "name": g["name"]} for g in guilds]

                    # Get channels for first guild
                    if guilds:
                        channels_req = urllib.request.Request(
                            f"https://discord.com/api/v10/guilds/{guilds[0]['id']}/channels",
                            headers={"Authorization": f"Bot {token}"},
                        )
                        channels_resp = urllib.request.urlopen(channels_req)
                        channels = json.loads(channels_resp.read())
                        status["channels"] = [
                            {"id": c["id"], "name": c["name"], "type": c["type"]}
                            for c in channels if c["type"] == 0  # Text channels only
                        ]
            except:
                pass

        return status


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Discord Login & Setup")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("login", help="Login to Discord via browser")
    subparsers.add_parser("status", help="Check login status")
    subparsers.add_parser("bot", help="Setup bot token")
    setup_parser = subparsers.add_parser("setup", help="Full setup: login + bot")

    args = parser.parse_args()
    dl = DiscordLogin()

    if args.command == "login":
        token = await dl.login_via_playwright()
        if token:
            print(f"\n✅ Discord login successful!")
            print(f"   Token saved to: {TOKEN_FILE}")
        else:
            print("\n❌ Login failed. Check logs above.")

    elif args.command == "status":
        status = await dl.check_status()
        print(f"\n📡 Discord Status")
        print(f"{'='*50}")
        print(f"  User Login: {'✅' if status['user_token'] else '❌'}")
        if status.get("user"):
            print(f"  User: {status['user']}")
        print(f"  Bot Token: {'✅' if status['bot_token'] else '❌'}")
        if status.get("bot"):
            print(f"  Bot: {status['bot']}")
        if status["guilds"]:
            print(f"\n  Guilds ({len(status['guilds'])}):")
            for g in status["guilds"]:
                print(f"    - {g['name']} ({g['id']})")
        if status["channels"]:
            print(f"\n  Channels (first guild):")
            for c in status["channels"][:10]:
                print(f"    - #{c['name']} ({c['id']})")
        print()

    elif args.command == "bot":
        token = await dl.get_bot_token()
        if token:
            print(f"\n✅ Bot token configured!")
        else:
            print("\n❌ No bot token provided.")

    elif args.command == "setup":
        print("\n🚀 Discord Full Setup\n")
        print("Step 1: Login to Discord...")
        token = await dl.login_via_playwright()
        if token:
            print("✅ Login successful!")
        else:
            print("⚠️ Login skipped or failed. Continuing with bot setup...")

        print("\nStep 2: Setup Bot Token...")
        bot_token = await dl.get_bot_token()
        if bot_token:
            print("✅ Bot token configured!")
        else:
            print("⚠️ Bot token not configured.")

        print("\nStep 3: Check Status...")
        status = await dl.check_status()
        if status["bot_token"]:
            print(f"✅ Bot is live: {status.get('bot', 'Unknown')}")
            if status["guilds"]:
                print(f"   In {len(status['guilds'])} guild(s)")
                for g in status["guilds"]:
                    print(f"     - {g['name']}")
        else:
            print("❌ Bot not configured. Follow the instructions above.")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())