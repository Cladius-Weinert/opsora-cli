---
name: opsora-growth
description: Local business growth operations — prospect research, outreach templates (Bahasa Indonesia), follow-up sequences, free audit templates. NO auto-send, NO spam.
---

# Skill: Local Growth Operator

Prepare manual outreach materials for local SMB targets in Bali/Indonesia. This skill generates prospect lists, outreach templates, and follow-up sequences — but NEVER auto-sends anything.

## When to use

- Researching prospects in a target area/segment
- Creating outreach templates (WhatsApp, email)
- Building follow-up sequences
- Preparing free audit offerings
- Creating demo proposals for specific businesses

## Target segments

| Segment | Key pain point | AI solution |
|---------|---------------|-------------|
| Klinik gigi / dentist | Missed appointment calls, slow response | AI receptionist + booking |
| Villa / hotel | Inquiry response time, multilingual | AI concierge + lead capture |
| Salon / spa | Booking chaos, no-show | AI scheduler + reminders |
| Rental mobil / motor | Price inquiries, availability | AI quote bot + calendar |
| Travel agent | Itinerary questions, follow-up | AI planner + CRM |

## Hard rules

1. **NO auto-send** — every message must be reviewed by a human before sending
2. **NO spam** — no mass messaging, no scraping contact lists
3. **Bahasa Indonesia** — all outreach templates in natural, friendly Indonesian
4. **No medical claims** — for clinics/dentists, never claim treatment outcomes
5. **No price fabrication** — never invent prices or discounts not authorized by the business owner
6. **No AI self-identification** — drafts should not say "saya adalah AI" or similar

## Outreach template structure

### WhatsApp first contact
```
Halo [Nama]! 👋

Saya [Nama Admin] dari Opsora. Kami membantu bisnis [segment] di [area] 
membalas calon customer lebih cepat dan otomatis.

[Bisnis Anda] bisa dapat:
✅ Balas otomatis 24/7 untuk pertanyaan umum
✅ Catat data calon customer otomatis  
✅ Follow-up konsisten tanpa lupa

Boleh saya kirim contoh demo gratis untuk [segment]? 
Cukup 5 menit untuk lihat hasilnya. 😊
```

### Follow-up sequence
| Day | Action | Channel |
|-----|--------|---------|
| 0 | First contact | WhatsApp |
| 1 | If no reply: gentle reminder | WhatsApp |
| 3 | Share relevant case study / testimonial | WhatsApp |
| 7 | Free audit offer | WhatsApp |
| 14 | Final follow-up + special offer | WhatsApp + Email |

## Free audit template

```
## Audit Gratis: [Business Name]

### Temuan:
1. **Response time:** [X menit/jam rata-rata]
   → Target: < 5 menit dengan AI
2. **Lead capture:** [Ada/Tidak ada form online]
   → Opportunity: auto-capture dari WhatsApp/IG
3. **Follow-up:** [Manual/Belum ada sistem]
   → Opportunity: automated follow-up sequence

### Estimasi improvement:
- Response time: [current] → < 5 menit
- Lead capture: [X% loss] → 95%+ capture rate
- Follow-up: [inconsistent] → 100% automated

### Next step:
Demo 15 menit untuk lihat langsung hasilnya.
Hubungi: [contact]
```

## Prospect research workflow

1. **Identify area** — Denpasar, Kuta, Seminyak, Ubud, Sanur
2. **Search segment** — Google Maps, Instagram, local directories
3. **Score prospect** — Business size, online presence, review count
4. **Prepare personalized template** — Customize with business name, segment, pain points
5. **Queue for human review** — Add to outreach tracker
6. **Human sends** — Admin reviews and sends manually

## Tools used

| Tool | Purpose |
|------|---------|
| `web_fetch` | Research prospects online (public info only) |
| `read_file` | Read prospect templates, playbooks |
| `write_file` | Generate outreach documents, CSV trackers |
| `run_command` | Run prospect scoring scripts |

## Reference files

| File | Content |
|------|---------|
| `opsora/docs/playbooks/*.md` | Per-segment AI receptionist configs |
| `opsora/docs/outreach/*.md` | Prospecting process, WhatsApp scripts |
| `opsora/docs/sales/*.md` | Discovery questions, demo scripts |
| `opsora/templates/*.md` | Client-facing documents |
