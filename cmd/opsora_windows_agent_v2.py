"""
Opsora Windows Agent v2 — Autonomous Browser Automation via SSM

Architecture:
Since SSM can't capture screenshots (no interactive desktop), we use
direct browser automation via PowerShell + Selenium/Playwright on Windows.

The AI agent:
1. Sends PowerShell commands via SSM to control browser
2. Extracts page content (text, links, emails) via DOM scraping
3. AI analyzes the extracted content
4. AI decides next action (click, navigate, type)
5. Repeat until task complete

This is MORE effective than screenshot-based approach because:
- No dependency on interactive desktop session
- Direct DOM access = better data extraction
- Faster (no screenshot upload/download cycle)
- Works even when no user is logged in

Usage:
    python3 opsora_windows_agent_v2.py "Check Gmail for unread emails"
    python3 opsora_windows_agent_v2.py "Open Outlook and summarize latest emails"
"""

import subprocess
import json
import time
import os
import sys
from typing import Optional

# AWS config
AWS_PROFILE = "default"
AWS_REGION = "us-west-2"
INSTANCE_ID = "i-00a029fb605878701"

# PowerShell templates
PS_OPEN_URL = '''
$chromePath = @(
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($chromePath) {{
    Start-Process $chromePath -ArgumentList "--new-window","{}" -PassThru
    Write-Output "Chrome opened: {}"
}} else {{
    # Try Edge as fallback
    Start-Process "msedge.exe" -ArgumentList "{}" -PassThru
    Write-Output "Edge opened: {}"
}}
'''

PS_GET_PAGE_CONTENT = '''
# Get content from active Chrome tab via CDP (Chrome DevTools Protocol)
$chromeDebugPort = 9222

# Check if Chrome is running with debug port
$chrome = Get-Process -Name chrome -ErrorAction SilentlyContinue
if ($chrome) {{
    # Try to get page content via CDP
    try {{
        $tabs = Invoke-RestMethod -Uri "http://localhost:$chromeDebugPort/json" -TimeoutSec 5
        if ($tabs) {{
            $firstTab = $tabs[0]
            $wsUrl = $firstTab.webSocketDebuggerUrl
            Write-Output "CDP found: $($firstTab.url)"
            Write-Output "Title: $($firstTab.title)"
        }} else {{
            Write-Output "No tabs found"
        }}
    }} catch {{
        Write-Output "CDP not available, Chrome not running with --remote-debugging-port"
    }}
}} else {{
    Write-Output "Chrome not running"
}}
'''

PS_NAVIGATE = '''
# Use Shell.Application to navigate in existing browser
$shell = New-Object -ComObject Shell.Application
$url = "{}"

# Try to find existing browser window
$browser = $shell.Windows() | Where-Object {{ $_.Name -match "Internet|Chrome|Edge" }} | Select-Object -First 1
if ($browser) {{
    $browser.Navigate($url)
    Start-Sleep -Seconds 3
    Write-Output "Navigated to: $url"
    Write-Output "Current URL: $($browser.LocationURL)"
    Write-Output "Title: $($browser.Document.title)"
}} else {{
    Start-Process "chrome.exe" -ArgumentList $url
    Start-Sleep -Seconds 5
    Write-Output "New Chrome window: $url"
}}
'''

PS_GET_PAGE_TEXT = '''
# Get visible text from active browser page using COM
$shell = New-Object -ComObject Shell.Application
$browser = $shell.Windows() | Where-Object {{ $_.Name -match "Internet|Chrome|Edge" }} | Select-Object -Last 1

if ($browser -and $browser.Document) {{
    try {{
        $doc = $browser.Document
        $body = $doc.body
        if ($body) {{
            $text = $body.innerText
            # Truncate to 5000 chars
            if ($text.Length -gt 5000) {{
                $text = $text.Substring(0, 5000) + "...(truncated)"
            }}
            Write-Output "URL: $($browser.LocationURL)"
            Write-Output "Title: $($doc.title)"
            Write-Output "---CONTENT---"
            Write-Output $text
        }} else {{
            Write-Output "Page not fully loaded"
        }}
    }} catch {{
        Write-Output "Could not access page content: $_"
    }}
}} else {{
    Write-Output "No browser window found"
}}
'''

PS_CLICK_ELEMENT = '''
# Click element by CSS selector using COM
$selector = "{}"
$shell = New-Object -ComObject Shell.Application
$browser = $shell.Windows() | Where-Object {{ $_.Name -match "Internet|Chrome|Edge" }} | Select-Object -Last 1

if ($browser -and $browser.Document) {{
    try {{
        $element = $browser.Document.querySelector($selector)
        if ($element) {{
            $element.click()
            Start-Sleep -Seconds 2
            Write-Output "Clicked: $selector"
        }} else {{
            Write-Output "Element not found: $selector"
        }}
    }} catch {{
        Write-Output "Click failed: $_"
    }}
}} else {{
    Write-Output "No browser window found"
}}
'''

PS_FILL_INPUT = '''
# Fill input field using COM
$selector = "{}"
$value = "{}"
$shell = New-Object -ComObject Shell.Application
$browser = $shell.Windows() | Where-Object {{ $_.Name -match "Internet|Chrome|Edge" }} | Select-Object -Last 1

if ($browser -and $browser.Document) {{
    try {{
        $input = $browser.Document.querySelector($selector)
        if ($input) {{
            $input.value = $value
            Write-Output "Filled $selector with value"
        }} else {{
            Write-Output "Input not found: $selector"
        }}
    }} catch {{
        Write-Output "Fill failed: $_"
    }}
}} else {{
    Write-Output "No browser window found"
}}
'''

PS_LIST_BROWSERS = '''
# List all browser processes and windows
Get-Process -Name "chrome","msedge","iexplore" -ErrorAction SilentlyContinue |
    Select-Object Id,ProcessName,CPU,WorkingSet64 | Format-Table -AutoSize

$shell = New-Object -ComObject Shell.Application
$shell.Windows() | Where-Object {{ $_.Name -match "Internet|Chrome|Edge" }} |
    ForEach-Object {{
        Write-Output "Window: $($_.Name) | URL: $($_.LocationURL) | Title: $($_.Document.title)"
    }}
'''

PS_START_CHROME_DEBUG = '''
# Start Chrome with remote debugging port for CDP access
$chromePaths = @(
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
)
$chromePath = $chromePaths | Where-Object {{ Test-Path $_ }} | Select-Object -First 1

if ($chromePath) {{
    # Kill existing Chrome
    Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 2
    # Start with debug port
    Start-Process $chromePath -ArgumentList "--remote-debugging-port=9222","--no-first-run","--no-default-browser-check","{}"
    Write-Output "Chrome started with debug port 9222: {}"
}} else {{
    Write-Output "Chrome not found"
}}
'''

PS_CDP_GET_CONTENT = '''
# Get page content via Chrome DevTools Protocol
try {{
    $tabs = Invoke-RestMethod -Uri "http://localhost:9222/json" -TimeoutSec 5
    if ($tabs -and $tabs.Count -gt 0) {{
        $tab = $tabs[0]
        Write-Output "URL: $($tab.url)"
        Write-Output "Title: $($tab.title)"

        # Get page source via CDP
        $wsUrl = $tab.webSocketDebuggerUrl
        # For simplicity, get via HTTP endpoint
        $pageUrl = "http://localhost:9222/json/list"
        $pages = Invoke-RestMethod -Uri $pageUrl -TimeoutSec 5
        Write-Output "Pages: $($pages.Count)"
        Write-Output "First page: $($pages[0].url)"
    }} else {{
        Write-Output "No tabs available"
    }}
}} catch {{
    Write-Output "CDP error: $_"
}}
'''


def run_ssm_command(commands: list[str], timeout: int = 60) -> dict:
    """Send command via SSM and wait for result"""
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
    for _ in range(timeout // 5):
        time.sleep(5)
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

    return {"error": "Timeout"}


def open_url(url: str) -> dict:
    """Open URL in Chrome"""
    return run_ssm_command([PS_OPEN_URL.format(url, url, url, url)], timeout=30)


def start_chrome_debug(url: str = "") -> dict:
    """Start Chrome with remote debugging port"""
    return run_ssm_command([PS_START_CHROME_DEBUG.format(url, url)], timeout=30)


def navigate(url: str) -> dict:
    """Navigate browser to URL"""
    return run_ssm_command([PS_NAVIGATE.format(url)], timeout=20)


def get_page_text() -> dict:
    """Get visible text from active browser page"""
    return run_ssm_command([PS_GET_PAGE_TEXT], timeout=20)


def get_page_content_cdp() -> dict:
    """Get page content via Chrome DevTools Protocol"""
    return run_ssm_command([PS_CDP_GET_CONTENT], timeout=20)


def click_element(selector: str) -> dict:
    """Click element by CSS selector"""
    return run_ssm_command([PS_CLICK_ELEMENT.format(selector)], timeout=15)


def fill_input(selector: str, value: str) -> dict:
    """Fill input field"""
    return run_ssm_command([PS_FILL_INPUT.format(selector, value)], timeout=15)


def list_browsers() -> dict:
    """List browser processes and windows"""
    return run_ssm_command([PS_LIST_BROWSERS], timeout=15)


# ============================================================================
# Agent
# ============================================================================

SYSTEM_PROMPT = """You are an autonomous browser assistant on a remote Windows machine.

## Available actions:
- "open_url": Open a URL in Chrome (starts new window)
- "navigate": Navigate existing browser to URL
- "get_page_text": Get visible text from current page
- "click": Click element by CSS selector
- "fill": Fill input field by CSS selector
- "list_browsers": List open browser windows
- "done": Task complete — summarize findings

## How to respond:
Respond with JSON only:
{
    "thought": "What you see and plan",
    "action": "open_url|navigate|get_page_text|click|fill|list_browsers|done",
    "url": "https://...",     // for open_url/navigate
    "selector": "input[name='q']", // for click/fill
    "value": "search term",   // for fill
    "summary": "..."          // for done: summarize findings
}

## Tips:
- Gmail URL: https://mail.google.com
- Outlook Web: https://outlook.office.com/mail
- If browser isn't open, use "open_url" first
- To extract email content, use "get_page_text" after navigation
- Be specific with selectors: "input[type='email']", "a[href*='compose']", etc.
"""


class WindowsBrowserAgent:
    def __init__(self, task: str):
        self.task = task
        self.max_iterations = 25
        self.iteration = 0

    def run(self):
        print(f"\n{'='*60}")
        print(f"🤖 Windows Browser Agent — Task: {self.task}")
        print(f"{'='*60}\n")

        # Check instance status
        result = subprocess.run(
            ["aws", "ssm", "describe-instance-information",
             "--profile", AWS_PROFILE, "--region", AWS_REGION,
             "--query", f"InstanceInformationList[?InstanceId=='{INSTANCE_ID}'].PingStatus",
             "--output", "text"],
            capture_output=True, text=True, timeout=15
        )
        if "Online" not in result.stdout:
            print(f"❌ Windows instance offline. Cannot proceed.")
            return

        print(f"✓ Windows instance online\n")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {self.task}\n\nStart by listing open browser windows."}
        ]

        while self.iteration < self.max_iterations:
            self.iteration += 1
            print(f"\n{'─'*40}")
            print(f"  🔄 Step {self.iteration}/{self.max_iterations}")
            print(f"{'─'*40}")

            # Call AI
            print(f"  🧠 AI deciding action...")
            action = self._call_ai(messages)

            if not action:
                print("  ❌ AI returned no valid action")
                continue

            thought = action.get("thought", "")[:150]
            act = action.get("action", "")
            print(f"  💭 {thought}")
            print(f"  🎯 Action: {act}")

            # Execute
            result = self._execute_action(action)
            result_str = str(result.get("StandardOutputContent", result.get("error", "")))[:1000]
            print(f"  📄 Result: {result_str[:200]}")

            # Add to conversation
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({
                "role": "user",
                "content": f"Action '{act}' result:\n{result_str}\n\nWhat's your next step?"
            })

            # Check done
            if act == "done":
                print(f"\n{'='*60}")
                print(f"✅ Task Complete!")
                print(f"{'='*60}")
                summary = action.get("summary", action.get("thought", "No summary"))
                print(f"\n{summary}")
                return

            time.sleep(2)

        print(f"\n{'='*60}")
        print(f"⏱️ Max iterations reached ({self.max_iterations})")
        print(f"{'='*60}")

    def _call_ai(self, messages: list) -> Optional[dict]:
        """Call AI provider"""
        from openai import OpenAI

        try:
            # Use NVIDIA (working provider)
            client = OpenAI(
                api_key=os.environ.get("NVIDIA_API_KEY"),
                base_url="https://integrate.api.nvidia.com/v1",
                timeout=60
            )
            resp = client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct",
                messages=messages,
                temperature=0.1,
                max_tokens=1000
            )
            content = resp.choices[0].message.content.strip()

            # Extract JSON
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

        if act == "open_url":
            url = action.get("url", "")
            print(f"  🌐 Opening: {url}")
            return start_chrome_debug(url)

        elif act == "navigate":
            url = action.get("url", "")
            print(f"  🌐 Navigating: {url}")
            return navigate(url)

        elif act == "get_page_text":
            print(f"  📄 Getting page content...")
            return get_page_text()

        elif act == "click":
            selector = action.get("selector", "")
            print(f"  🖱️  Clicking: {selector}")
            return click_element(selector)

        elif act == "fill":
            selector = action.get("selector", "")
            value = action.get("value", "")
            print(f"  ⌨️  Filling: {selector} = {value[:30]}...")
            return fill_input(selector, value)

        elif act == "list_browsers":
            print(f"  📋 Listing browsers...")
            return list_browsers()

        elif act == "done":
            print(f"  ✅ Done")
            return {"status": "done"}

        return {"error": f"Unknown action: {act}"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 opsora_windows_agent_v2.py '<task>'")
        print("\nExamples:")
        print("  python3 opsora_windows_agent_v2.py 'Check Gmail for unread emails'")
        print("  python3 opsora_windows_agent_v2.py 'Open Outlook and summarize latest emails'")
        print("  python3 opsora_windows_agent_v2.py 'Go to gmail.com and tell me inbox summary'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    agent = WindowsBrowserAgent(task)
    agent.run()
