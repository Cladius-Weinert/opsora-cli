# 🤖 Opsora Windows Agent — Autonomous Browser Control

AI agent yang bisa **kontrol browser di Windows instance** secara autonomous via SSM — seperti OpenClaw.

## Cara Kerja

```
AI Agent (opsora-brain)
    ↓ SSM (PowerShell)
  ┌─────────────────────────────────┐
  │  Windows Instance (us-west-2)   │
  │  • Buka Chrome/Edge             │
  │  • Navigasi ke URL              │
  │  • Baca content halaman (DOM)   │
  │  • Klik element                 │
  │  • Isi form                     │
  └─────────────────────────────────┘
    ↓ content dikirim balik
AI analisa → putuskan langkah berikut
```

## Quick Start

```bash
# Cek Gmail
win-agent "Check Gmail for unread emails and summarize them"

# Baca Outlook
win-agent "Open Outlook and tell me the latest 3 emails"

# Research
win-agent "Go to google.com and search for 'AI coding assistants 2025'"

# Custom task
win-agent "Navigate to https://mail.google.com and tell me what you see"
```

## Available Actions

| Action | Deskripsi |
|--------|-----------|
| `open_url` | Buka URL di Chrome (new window + debug mode) |
| `navigate` | Navigasi browser yang sudah terbuka ke URL baru |
| `get_page_text` | Extract semua teks dari halaman aktif |
| `click` | Klik element by CSS selector |
| `fill` | Isi input field by CSS selector |
| `list_browsers` | List browser yang sedang terbuka |
| `done` | Task selesai — AI summarize findings |

## Arsitektur

### Kenapa bukan screenshot-based?
SSM berjalan di **non-interactive session** — tidak ada desktop untuk di-capture. Solusi:
- **Browser automation via COM/CDP** — langsung akses DOM browser
- **Chrome DevTools Protocol** — remote debugging untuk full browser control
- **PowerShell COM objects** — Shell.Application untuk navigasi browser

### Flow per Iteration
1. AI putuskan action berikutnya (JSON response)
2. Kirim PowerShell command via SSM
3. Terima hasil (text content, navigation status, dll)
4. AI analisa hasil → putuskan action lagi
5. Ulangi sampai task selesai atau max iterations

### Target Windows Instance
- **Instance**: `i-00a029fb605878701` (rdp-windows-prod)
- **Region**: us-west-2
- **IP**: 35.166.137.207
- **Platform**: Windows Server 2022
- **Browsers**: Chrome, Edge (pre-installed)
- **SSM**: ✅ Online

## Contoh Use Cases

### 1. Cek Email
```bash
win-agent "Go to Gmail and tell me how many unread emails I have"
```
Agent akan:
1. Buka Chrome → navigate ke gmail.com
2. Extract page content → cari unread count
3. Report hasilnya

### 2. Research Web
```bash
win-agent "Search Google for 'best AI coding tools' and summarize top 5 results"
```

### 3. Monitor Dashboard
```bash
win-agent "Open Datadog dashboard and tell me current alert status"
```

### 4. Form Filling
```bash
win-agent "Go to example.com/login and check if login page is working"
```

## Limitations

| Limitation | Workaround |
|------------|------------|
| Screenshot tidak bisa via SSM | Pakai DOM extraction instead |
| Login butuh cookies/session | User harus login manual sekali |
| COM access terbatas ke browser | Chrome CDP untuk full control |
| Max 25 iterations per task | Cukup untuk kebanyakan tasks |

## Files

| File | Purpose |
|------|---------|
| `opsora_windows_agent_v2.py` | Main agent (browser automation) |
| `opsora_windows_agent.py` | Original (screenshot-based, deprecated) |

## Alias
```bash
win-agent "<task>"    # Run Windows browser agent
```
