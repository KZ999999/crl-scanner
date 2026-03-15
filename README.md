# CRL Scanner

Monitors FDA's Complete Response Letters API every 20 minutes. Detects new CRLs and status changes, sends alerts via n8n webhook to Gmail.

## What it monitors

| Alert | Trigger | Meaning |
|-------|---------|---------|
| **New CRL** | New `application_number` + `letter_date` appears | A company just got hit with a Complete Response Letter |
| **Status flip** | `approval_status` changes `Unapproved` → `Approved` | A previously rejected drug is now approved |

## How it works

```
Every 20 min (Render cron):
  1. Fetch all CRLs from FDA API (?limit=1000)
  2. Load previous snapshot from Supabase
  3. Diff → find new records + status changes
  4. If changes → POST to n8n webhook → Gmail
  5. Upsert all records to Supabase
  First run seeds the DB with all existing records (no false alerts).
```

## Setup

### 1. Supabase
- Create a project at supabase.com
- Go to SQL Editor → run `setup.sql`
- Copy your project URL and anon key

### 2. n8n
- Create workflow: **Webhook trigger** → **Gmail node**
- Copy the webhook URL
- Email template:

```
Subject: FDA CRL Alert — {{$json.summary.new_crl_count}} new, {{$json.summary.status_change_count}} status changes

New CRLs:
{{$json.new_crls.map(c => `• ${c.application_number} — ${c.company_name} (${c.letter_date})`).join('\n')}}

Status Changes:
{{$json.status_changes.map(c => `• ${c.application_number} — ${c.company_name}: ${c.old_status} → ${c.new_status}`).join('\n')}}
```

### 3. Render
- Push this repo to GitHub
- Render → New → Blueprint → connect repo
- Set 3 env vars in dashboard:

```
SUPABASE_URL = https://xxxxx.supabase.co
SUPABASE_KEY = your-anon-key
N8N_WEBHOOK_URL = https://your-n8n/webhook/xxxxx
```

### 4. Test
- Trigger first run manually in Render → seeds Supabase (no alerts)
- To test alerts: manually edit a row in Supabase (change `approval_status` or delete a row)
- Next run will detect the diff and fire the webhook

## Webhook payload format

```json
{
  "new_crls": [
    {
      "application_number": "NDA 220140",
      "company_name": "Rosemont Pharmaceuticals",
      "letter_date": "03/05/2026",
      "approval_status": "Unapproved",
      "letter_type": "COMPLETE RESPONSE",
      "pdf_url": "https://download.open.fda.gov/crl/CRL_NDA220140_20260305.pdf"
    }
  ],
  "status_changes": [
    {
      "application_number": "BLA 761299",
      "company_name": "Alvotech",
      "letter_date": "06/28/2023",
      "old_status": "Unapproved",
      "new_status": "Approved"
    }
  ],
  "summary": {
    "new_crl_count": 1,
    "status_change_count": 1
  }
}
```

## Cost
- Render cron: $7/month (Starter)
- Supabase: free tier
- n8n: depends on hosting (self-hosted = free)

## Files
```
scanner.py         — the scanner (only real code)
setup.sql          — Supabase table creation
render.yaml        — Render cron config (every 20 min)
requirements.txt   — Python dependencies
.gitignore         — ignores local files
```
