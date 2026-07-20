"""
Opsora Windows Agent v3 — Headless Browser via SSM

Uses Playwright on Windows to run headless browser - no desktop needed.
Works in SSM non-interactive session.
"""

import subprocess
import json
import time
import os
import sys
from typing import Optional

AWS_PROFILE = "default"
AWS_REGION = "us-west-2"
INSTANCE_ID = "i-00a029fb605878701"

# Playwright PowerShell scripts - headless, works in SSM
PS_INSTALL_PLAYWRIGHT = '''
# Install Playwright for PowerShell
if (!(Get-Module -ListAvailable -Name Playwright)) {{
    Install-Module -Name Playwright -Force -Scope CurrentUser
    pwsh -Command "Microsoft.Playwright.Program.Installer" 2>$null
}}
Write-Output "Playwright ready"
'''

PS_GMAIL_CHECK = '''
# Check Gmail using headless browser
$url = "https://mail.google.com"
$timeout = 30000

Add-Type -AssemblyName System.Web

try {{
    # Use Invoke-WebRequest first to check auth status
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $response = Invoke-WebRequest -Uri $url -WebSession $session -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
    Write-Output "STATUS: $($response.StatusCode)"
    Write-Output "URL: $($response.BaseResponse.ResponseUri.AbsoluteUri)"

    # Check if redirected to login
    $finalUrl = $response.BaseResponse.ResponseUri.AbsoluteUri
    if ($finalUrl -match "accounts.google.com") {{
        Write-Output "RESULT: Not logged in - redirect to Google login"
        Write-Output "LOGIN_URL: $finalUrl"
    }} elseif ($finalUrl -match "mail.google.com") {{
        Write-Output "RESULT: Logged in to Gmail"
        # Extract page content
        $content = $response.Content
        if ($content -match "Inbox") {{
            Write-Output "GMAIL_STATUS: Inbox accessible"
        }}
        # Look for email count patterns
        if ($content -match "(\d+\s*(unread|new))") {{
            Write-Output "UNREAD_HINT: $($Matches[1])"
        }}
    }} else {{
        Write-Output "RESULT: Redirected to $finalUrl"
    }}
}} catch {{
    Write-Output "ERROR: $_"
    Write-Output "FALLBACK: Trying direct Gmail access..."

    # Try with curl-like approach
    try {{
        $resp2 = Invoke-WebRequest -Uri "https://mail.google.com/mail/" -TimeoutSec 15 -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
    }} catch [System.Net.WebException] {{
        $resp2 = $_.Exception.Response
        if ($resp2) {{
            Write-Output "HTTP_STATUS: $($resp2.StatusCode)"
            Write-Output "REDIRECT: $($resp2.Headers.Location)"
        }}
    }}
}}
'''

PS_GOOGLE_ACCOUNTS = '''
# Check Google accounts on this machine
$regPath = "HKLM:\SOFTWARE\Google\Chrome\PreferenceMACs"
if (Test-Path $regPath) {{
    Get-ChildItem $regPath -Recurse | Where-Object {{ $_.PSChildName -match "account" }} | ForEach-Object {{
        Write-Output "Registry: $($_.PSPath) = $($_.GetValue())"
    }}
}} else {{
    Write-Output "No Chrome Google accounts in registry"
}}

# Check if there are any Google credential files
$googlePaths = @(
    "$env:LOCALAPPDATA\Google",
    "$env:APPDATA\Google"
)
foreach ($p in $googlePaths) {{
    if (Test-Path $p) {{
        Write-Output "Google config exists at: $p"
        Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {{ $_.Name -match "token|credential|login|auth" }} |
            ForEach-Object {{ Write-Output "  Found: $($_.FullName)" }}
    }}
}}

# Check Windows Credential Manager for Google entries
cmd /c "cmdkey /list 2>nul | findstr /i google" 2>$null
'''

PS_CHECK_EMAILS_VIA_IMAP = '''
# Try to access Gmail via IMAP (if app password configured)
# This is an alternative when browser access is not available

$gmailIMAP = "imap.gmail.com"
$port = 993

try {{
    $tcp = New-Object System.Net.Sockets.TcpClient($gmailIMAP, $port)
    $stream = $tcp.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    # Read greeting
    $greeting = $reader.ReadLine()
    Write-Output "IMAP: $greeting"
    Write-Output "IMAP_STATUS: Server reachable on port 993"
    Write-Output "NOTE: Need email + app password to login"

    $tcp.Close()
}} catch {{
    Write-Output "IMAP_ERROR: $_"
}}
'''


def run_ssm_command(commands: list[str], timeout: int = 60) -> dict:
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


def check_gmail_access() -> dict:
    """Check Gmail login status"""
    return run_ssm_command([PS_GMAIL_CHECK], timeout=30)


def check_google_accounts() -> dict:
    """Check Google accounts configured on Windows"""
    return run_ssm_command([PS_GOOGLE_ACCOUNTS], timeout=20)


def check_imap() -> dict:
    """Check if Gmail IMAP is reachable"""
    return run_ssm_command([PS_CHECK_EMAILS_VIA_IMAP], timeout=20)


def main():
    print("\n" + "="*60)
    print("🔍 Gmail Access Diagnostic")
    print("="*60 + "\n")

    # Check instance
    result = subprocess.run(
        ["aws", "ssm", "describe-instance-information",
         "--profile", AWS_PROFILE, "--region", AWS_REGION,
         "--query", f"InstanceInformationList[?InstanceId=='{INSTANCE_ID}'].PingStatus",
         "--output", "text"],
        capture_output=True, text=True, timeout=15
    )
    if "Online" not in result.stdout:
        print("❌ Windows instance offline")
        return

    print("✓ Windows instance online\n")

    # 1. Check Google accounts on Windows
    print("1️⃣  Checking Google accounts on Windows...")
    result = check_google_accounts()
    output = result.get("StandardOutputContent", "")
    print(f"   {output.strip()[:500]}")
    print()

    # 2. Check Gmail access
    print("2️⃣  Checking Gmail access...")
    result = check_gmail_access()
    output = result.get("StandardOutputContent", "")
    print(f"   {output.strip()[:1000]}")
    print()

    # 3. Check IMAP
    print("3️⃣  Checking Gmail IMAP...")
    result = check_imap()
    output = result.get("StandardOutputContent", "")
    print(f"   {output.strip()[:500]}")
    print()

    print("="*60)
    print("📋 Summary & Next Steps")
    print("="*60)
    print("""
If Gmail shows "Not logged in":
  → You need to login via browser first (use Guacamole RDP)
  → After login, cookies will persist

If Gmail shows "Logged in":
  → We can use the session cookies for automated access

If Google accounts found in registry:
  → Account is configured in Chrome on Windows
  → Open Chrome with --profile-directory to use it

For automated email access:
  Option A: Setup Gmail API with OAuth token
  Option B: Setup IMAP with App Password
  Option C: Use Guacamole RDP for manual login once, then automate
    """)


if __name__ == "__main__":
    main()
