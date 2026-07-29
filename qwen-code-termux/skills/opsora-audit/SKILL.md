---
name: opsora-audit
description: Audit ekosistem Opsora — secret status, repos, health check, export konteks Qwen. Aman (masked), tidak expose key di chat.
---

# Skill: Opsora Audit

Jalankan skill ini di awal sesi Qwen Code atau saat butuh orientasi cepat di ekosistem Opsora.

## Kapan dipakai

- Baru mulai kerja di proyek Opsora
- Tidak yakin secret mana yang sudah terisi
- Butuh konteks repo/path sebelum coding
- Ingin load memory tanpa baca 500 baris manual

## Langkah cepat

```bash
# 1. Audit lengkap
opsora-audit all

# 2. Export konteks untuk Qwen
opsora-audit export

# 3. Jalankan Qwen dengan konteks
opsora-qwen-model power
opsora-qwen
# Di dalam Qwen: @~/.opsora/qwen-code/context-bundle.md
```

## Sub-perintah

| Perintah | Fungsi |
|----------|--------|
| `secrets` | Status env var (masked: `sk-ab...xy12`) |
| `repos` | 6 repo: cloned?, branch, commits 2 hari |
| `clone` | Clone semua repo ke `$QWEN_PROJECTS_DIR` |
| `health` | Test NVIDIA, DashScope, URL produksi |
| `export` | Buat `context-bundle.md` (aman, no full secrets) |
| `reveal` | Tulis nilai penuh ke file lokal PRIVAT saja |
| `context` | Daftar path memory/settings/agents |
| `all` | Semua di atas |

## Nilai secret (LOKAL SAJA)

Jika perlu lihat nilai penuh di device sendiri (bukan di chat AI):

```bash
opsora-audit reveal --yes-i-understand
cat ~/.opsora/private/credentials.snapshot
rm ~/.opsora/private/credentials.snapshot   # hapus setelah dipakai
```

**Jangan** paste isi snapshot ke chat Qwen/Cursor.

## Install skill ke Qwen

```bash
cp ~/opsora-cli/qwen-code-termux/agents/opsora-audit.md ~/.qwen/agents/
chmod +x ~/opsora-cli/qwen-code-termux/opsora-audit.sh
# Wrapper sudah terpasang via install-termux.sh → opsora-audit
```

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `DASHSCOPE_API_KEY MISSING` | `nano ~/.opsora/qwen-code/secrets.env` |
| Repo NOT CLONED | `opsora-audit clone` |
| NVIDIA HTTP 401 | Cek/regenerate key di NGC |
| Memory file tidak ada | `cd ~/opsora-cli && git pull` |

## Performance Notes

- `secrets` + `repos` < 2 detik
- `health` ~5–15 detik (network)
- `all` ~20 detik total

## Examples

**Onboarding sesi baru:**
```
User: "cek setup opsora"
→ Jalankan: opsora-audit all
→ Load: @context-bundle.md
→ Lanjut kerja di repo yang relevan
```

**Sebelum deploy landing:**
```
opsora-audit secrets | grep OPSORA_LEAD
opsora-audit health
```
