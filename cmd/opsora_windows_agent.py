"""
Opsora Windows Remote Agent — Autonomous Screen Control via SSM

Architecture:
1. Take screenshot on Windows via SSM
2. Upload screenshot to S3
3. Download screenshot here
4. AI vision analyses what's on screen
5. AI decides next action (click, type, scroll)
6. Send mouse/keyboard command via SSM
7. Repeat until task complete

Usage:
    python3 opsora_windows_agent.py "Check my Gmail for unread emails"
    python3 opsora_windows_agent.py "Open Outlook and read latest emails"
"""

import subprocess
import json
import time
import base64
import os
import sys
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# S3 bucket for screenshot exchange
S3_BUCKET = "opsora-agent-screenshots"
S3_KEY_PREFIX = "screenshots"

# AWS config
AWS_PROFILE = "default"
AWS_REGION = "us-west-2"
INSTANCE_ID = "i-00a029fb605878701"

# Screenshot path on Windows
WIN_SCREENSHOT = "C:\\temp\\screen.png"
WIN_SCREENSHOT_S3 = f"s3://{S3_BUCKET}/{S3_KEY_PREFIX}/"

# PowerShell scripts
PS_SCREENSHOT = r'''
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$bitmap = New-Object System.Drawing.Bitmap($screen.Bounds.Width, $screen.Bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Bounds.X, $screen.Bounds.Y, 0, 0, $screen.Bounds.Size)
$bitmap.Save("{}","System.Drawing.Imaging.ImageFormat::Png")
$bitmap.Dispose()
$graphics.Dispose()
Write-Output "Screenshot saved: {}x{}"
'''.format(WIN_SCREENSHOT, "$screen.Bounds.Width", "$screen.Bounds.Height")

PS_MOUSE_CLICK = r'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({}, {})
Start-Sleep -Milliseconds 100
[Windows.Forms.Cursor]::Position
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Mouse {{
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, int dwExtraInfo);
    public static void Click() {{ mouse_event(0x0002 | 0x0004, 0, 0, 0, 0); }}
}}
"@
[Mouse]::Click()
Write-Output "Clicked at ({}, {})"
'''.format("{}", "{}", "{}", "{}")

PS_TYPE_TEXT = r'''
Add-Type -AssemblyName System.Windows.Forms
$text = "{}"
[System.Windows.Forms.SendKeys]::SendWait($text)
Write-Output "Typed: $text"
'''.format("{}")

PS_KEY_PRESS = r'''
Add-Type -AssemblyName System.Windows.Forms
$key = "{}"
[System.Windows.Forms.SendKeys]::SendWait("{{$key}}")
Write-Output "Pressed: $key"
'''.format("{}")

PS_GET_MOUSE_POS = r'''
Add-Type -AssemblyName System.Windows.Forms
$pos = [System.Windows.Forms.Cursor]::Position
Write-Output "$($pos.X),$($pos.Y)"
'''

PS_OPEN_BROWSER = r'''
Start-Process "chrome.exe" "{}"
Write-Output "Browser opened: {}"
'''

PS_LIST_WINDOWS = r'''
Get-Process | Where-Object {$_.MainWindowTitle -ne ""} | Select-Object Id,ProcessName,MainWindowTitle | Format-Table -AutoSize
'''


def run_ssm_command(commands: list[str], timeout: int = 60) -> dict:
    """Send command via SSM and wait for result"""
    # Send command
    result = subprocess.run(
        [
            "aws", "ssm", "send-command",
            "--profile", AWS_PROFILE,
            "--region", AWS_REGION,
            "--instance-ids", INSTANCE_ID,
            "--document-name", "AWS-RunPowerShellScript",
            "--parameters", f"commands={json.dumps(commands)}",
            "--output", "json",
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return {"error": result.stderr}

    cmd_data = json.loads(result.stdout)
    command_id = cmd_data["Command"]["CommandId"]

    # Wait for completion
    max_wait = timeout
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5

        result = subprocess.run(
            [
                "aws", "ssm", "get-command-invocation",
                "--profile", AWS_PROFILE,
                "--region", AWS_REGION,
                "--command-id", command_id,
                "--instance-id", INSTANCE_ID,
                "--output", "json",
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        invocation = json.loads(result.stdout)
        status = invocation.get("Status", "")

        if status in ("Success", "Failed", "TimedOut", "Cancelled"):
            return invocation

    return {"error": "Timeout waiting for command"}


def capture_screenshot() -> Optional[Path]:
    """Capture screenshot from Windows, download it locally"""
    screenshot_id = str(uuid.uuid4())[:8]
    local_path = Path(f"/tmp/screenshot_{screenshot_id}.png")
    s3_path = f"{WIN_SCREENSHOT_S3}{screenshot_id}.png"

    print(f"  📸 Capturing screenshot...")

    # Take screenshot on Windows
    result = run_ssm_command([PS_SCREENSHOT], timeout=30)
    if "error" in result:
        print(f"  ❌ Screenshot failed: {result['error'][:200]}")
        return None

    # Upload to S3 from Windows
    upload_cmd = f'aws s3 cp "{WIN_SCREENSHOT}" "{s3_path}" --profile {AWS_PROFILE}'
    run_ssm_command([upload_cmd], timeout=30)

    # Download locally
    result = subprocess.run(
        ["aws", "s3", "cp", s3_path, str(local_path),
         "--profile", AWS_PROFILE],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode == 0 and local_path.exists():
        print(f"  ✓ Screenshot saved: {local_path} ({local_path.stat().st_size:,} bytes)")
        return local_path

    print(f"  ❌ Download failed")
    return None


def click_at(x: int, y: int) -> dict:
    """Move mouse and click at coordinates"""
    cmd = PS_MOUSE_CLICK.format(x, y, x, y)
    return run_ssm_command([cmd], timeout=15)


def type_text(text: str) -> dict:
    """Type text using SendKeys"""
    # Escape special SendKeys characters
    escaped = text.replace("{", "{{}").replace("}", "{}}").replace("+", "{+}").replace("^", "{^}").replace("%", "{%}")
    cmd = PS_TYPE_TEXT.format(escaped)
    return run_ssm_command([cmd], timeout=15)


def press_key(key: str) -> dict:
    """Press a specific key"""
    cmd = PS_KEY_PRESS.format(key)
    return run_ssm_command([cmd], timeout=15)


def open_url(url: str) -> dict:
    """Open URL in Chrome"""
    cmd = PS_OPEN_BROWSER.format(url, url)
    return run_ssm_command([cmd], timeout=15)


def list_active_windows() -> dict:
    """List all windows with titles"""
    return run_ssm_command([PS_LIST_WINDOWS], timeout=15)


def get_mouse_pos() -> Optional[tuple]:
    """Get current mouse position"""
    result = run_ssm_command([PS_GET_MOUSE_POS], timeout=10)
    if "StandardOutputContent" in result:
        output = result["StandardOutputContent"].strip()
        try:
            x, y = map(int, output.split(","))
            return (x, y)
        except:
            pass
    return None


# ============================================================================
# Agent Loop
# ============================================================================

SYSTEM_PROMPT = """You are an autonomous Windows desktop assistant. You can see the screen and control the mouse/keyboard.

## Your capabilities:
- See screenshots of the Windows desktop
- Move mouse and click
- Type text
- Press keys (Enter, Tab, Ctrl+A, etc.)
- Open URLs in browser
- List active windows

## How to respond:
Respond with JSON only, in this format:
{
    "thought": "What you see and what you'll do next",
    "action": "click|type|key|open_url|list_windows|done",
    "x": 100,        // for click: x coordinate
    "y": 200,        // for click: y coordinate
    "text": "hello", // for type: text to type
    "key": "Enter",  // for key: key to press
    "url": "https://...", // for open_url
    "done": true     // set true when task is complete
}

## Important:
- Coordinates are in the screenshot's pixel dimensions
- Be careful with clicks — identify buttons/links visually
- For Gmail/Outlook, you may need to navigate through login first
- If browser is not open, use open_url action
- When task is complete, set "done": true and describe findings
"""


class WindowsAgent:
    def __init__(self, task: str):
        self.task = task
        self.history = []
        self.max_iterations = 20
        self.iteration = 0

    def run(self):
        print(f"\n{'='*60}")
        print(f"🤖 Windows Agent — Task: {self.task}")
        print(f"{'='*60}\n")

        # Check if instance is online
        result = subprocess.run(
            ["aws", "ssm", "describe-instance-information",
             "--profile", AWS_PROFILE, "--region", AWS_REGION,
             "--query", f"InstanceInformationList[?InstanceId=='{INSTANCE_ID}'].PingStatus",
             "--output", "text"],
            capture_output=True, text=True, timeout=15
        )
        if "Online" not in result.stdout:
            print(f"❌ Windows instance is not online. Cannot proceed.")
            return

        print(f"✓ Windows instance is online\n")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {self.task}\n\nFirst, take a screenshot to see the current desktop state."}
        ]

        while self.iteration < self.max_iterations:
            self.iteration += 1
            print(f"\n{'─'*40}")
            print(f"  🔄 Iteration {self.iteration}/{self.max_iterations}")
            print(f"{'─'*40}")

            # Capture screenshot
            screenshot_path = capture_screenshot()
            if not screenshot_path:
                print("  ⚠ Could not capture screenshot, continuing...")
                continue

            # Get screen dimensions
            from PIL import Image
            img = Image.open(screenshot_path)
            width, height = img.size
            print(f"  📐 Screen: {width}x{height}")

            # Build message with screenshot reference
            user_msg = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Current desktop screenshot ({width}x{height}). Task: {self.task}\n\nWhat do you see and what action should you take next?"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64.b64encode(screenshot_path.read_bytes()).decode()}"
                        }
                    }
                ]
            }

            messages.append(user_msg)

            # Call AI to decide next action
            print(f"  🧠 AI thinking...")
            # Use available AI provider
            action = self._call_ai(messages)

            if not action:
                print("  ❌ AI did not return valid action")
                continue

            print(f"  💭 Thought: {action.get('thought', 'N/A')[:150]}")
            print(f"  🎯 Action: {action.get('action', 'none')}")

            # Execute action
            result = self._execute_action(action)
            messages.append({
                "role": "assistant",
                "content": json.dumps(action)
            })
            messages.append({
                "role": "user",
                "content": f"Action result: {str(result)[:500]}\n\nTake another screenshot to see the result."
            })

            # Check if done
            if action.get("done") or action.get("action") == "done":
                print(f"\n{'='*60}")
                print(f"✅ Task Complete!")
                print(f"{'='*60}")
                print(f"\n{action.get('thought', 'No summary')}")
                break

            # Small delay for UI to update
            time.sleep(2)

        print(f"\n{'='*60}")
        print(f"🏁 Agent finished after {self.iteration} iterations")
        print(f"{'='*60}")

    def _call_ai(self, messages: list) -> Optional[dict]:
        """Call AI provider to get next action"""
        # Try OpenAI-compatible endpoint (Model Studio)
        from openai import OpenAI

        try:
            client = OpenAI(
                api_key=os.environ.get("DASHSCOPE_API_KEY"),
                base_url="https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
                timeout=60
            )
            resp = client.chat.completions.create(
                model="qwen-vl-plus",  # Vision model
                messages=messages,
                temperature=0.1,
                max_tokens=1000
            )
            content = resp.choices[0].message.content.strip()
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception as e:
            print(f"  ⚠ AI call failed: {e}")
            return None

    def _execute_action(self, action: dict) -> dict:
        """Execute the decided action"""
        act = action.get("action", "")

        if act == "click":
            x, y = action.get("x", 0), action.get("y", 0)
            print(f"  🖱️  Clicking at ({x}, {y})...")
            return click_at(x, y)

        elif act == "type":
            text = action.get("text", "")
            print(f"  ⌨️  Typing: {text[:50]}...")
            return type_text(text)

        elif act == "key":
            key = action.get("key", "")
            print(f"  ⌨️  Pressing: {key}")
            return press_key(key)

        elif act == "open_url":
            url = action.get("url", "")
            print(f"  🌐 Opening: {url}")
            return open_url(url)

        elif act == "list_windows":
            print(f"  📋 Listing windows...")
            return list_active_windows()

        elif act == "done":
            print(f"  ✅ Task marked as done")
            return {"status": "done"}

        return {"error": f"Unknown action: {act}"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 opsora_windows_agent.py 'Check my Gmail for new emails'")
        print("\nExamples:")
        print("  python3 opsora_windows_agent.py 'Check my Gmail for unread emails'")
        print("  python3 opsora_windows_agent.py 'Open Outlook and read the latest email'")
        print("  python3 opsora_windows_agent.py 'Go to gmail.com and tell me how many unread emails I have'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    agent = WindowsAgent(task)
    agent.run()
