---
name: opsora-crm
description: CRM and lead management engineering — NDJSON handling, CSV export, lead scoring, pipeline management, masked phone display. Based on OperatorOS API (Fastify + SQLite) and Supabase schemas.
---

# Skill: CRM Engineer

Build and improve the CRM/lead management system. Two CRM implementations exist in the ecosystem — use their patterns and schemas as reference.

## When to use

- Working on lead capture, storage, or retrieval
- Building/improving the admin dashboard
- Adding lead scoring or follow-up logic
- Exporting data (CSV, JSON)
- Integrating with WhatsApp (WATI) or email (Resend)

## Reference implementations

| System | Stack | Location |
|--------|-------|----------|
| OperatorOS | Fastify 5 + SQLite + scrypt auth | `opsora/operatoros/apps/api/` |
| opsora-dashboard | Next.js 16 + Supabase + RLS | `opsora-dashboard/` |

## Database schema (OperatorOS)

Key tables from `operatoros/apps/api/src/db/schema.sql`:

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `workspaces` | Multi-tenant isolation | id, name, slug |
| `businesses` | Client businesses | id, workspace_id, name, segment, phone |
| `leads` | Incoming leads | id, business_id, name, phone, source, status, created_at |
| `messages` | Conversation history | id, lead_id, direction, body, timestamp |
| `followups` | Scheduled follow-ups | id, lead_id, due_at, status, draft |
| `pipeline_events` | Status change audit | id, lead_id, from_status, to_status, at |
| `subscriptions` | Client plans | id, workspace_id, plan, monthly_fee, status |
| `invoices` | Billing records | id, workspace_id, period, amount, status |

## Lead pipeline statuses

```
new → contacted → booking_requested → booked → won
                                       ↘ lost
```

Every status change creates a `pipeline_event` for audit trail.

## Hard rules

1. **Never auto-send WhatsApp/email** — all outbound messages require human approval
2. **Phone numbers** — normalize to Indonesian format (62 prefix), mask in UI (`0812-****-5678`)
3. **AI drafts** — always in Bahasa Indonesia, no medical claims, no price fabrication, no booking confirmation
4. **Secret tokens** — `OPSORA_LEAD_API_TOKEN` is server-side only, never expose to client

## Lead scoring algorithm

From `opsora/scripts/opsora-lead-score.py`:

| Factor | Weight | Criteria |
|--------|--------|----------|
| Urgency | 30% | Keywords: "segera", "urgent", "besok", "hari ini" |
| Business fit | 25% | Matches target segment (clinic, villa, salon, etc.) |
| Need detail | 25% | Describes specific needs vs generic inquiry |
| Booking intent | 20% | Asks about price, availability, location |

Score 0-100, categorized: Hot (>70), Warm (40-70), Cold (<40)

## CSV export format

From `opsora/scripts/opsora-export-leads-csv.py`:

```csv
date,name,phone,source,business,status,score,notes
2026-07-28,Budi,0812****5678,landing-form,dental-clinic,new,72,Inquiry about teeth whitening
```

## WhatsApp handoff flow

1. Lead arrives → AI generates draft reply (Bahasa Indonesia)
2. Admin reviews draft in dashboard
3. Admin edits if needed → clicks "Approve & Send"
4. WATI API sends message → status updated to `contacted`
5. Follow-up scheduled automatically (24h, 72h, 7d)

## Tools used

| Tool | Purpose |
|------|---------|
| `read_file` | Read schema.sql, service files, scripts |
| `grep_search` | Find route handlers, database queries, API endpoints |
| `edit_file` | Modify services, add routes, update queries |
| `run_command` | Run migrations, test API endpoints, export data |
