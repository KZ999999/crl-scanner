"""
FDA CRL Scanner — monitors Complete Response Letters every 20 minutes.
Detects:
  1. New CRL records (new application_number + letter_date)
  2. Status flips (Unapproved → Approved)
Sends alerts to n8n webhook, stores state in Supabase.
"""

import os
import requests
from supabase import create_client

# --- Config ---
FDA_API_URL = "https://api.fda.gov/transparency/crl.json"
PDF_BASE_URL = "https://download.open.fda.gov/crl"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")


def fetch_all_crls():
    """Fetch all CRL records from FDA API."""
    print("Fetching all CRLs from FDA API...")
    resp = requests.get(f"{FDA_API_URL}?limit=1000", timeout=60)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    total = data.get("meta", {}).get("results", {}).get("total", 0)
    print(f"  Got {len(results)} records (total in DB: {total})")
    return results


def make_key(r):
    """Composite key: application_number + letter_date."""
    apps = r.get("application_number", [])
    app = apps[0] if isinstance(apps, list) and apps else str(apps)
    return f"{app}|{r.get('letter_date', '')}"


def parse_record(r):
    """Extract the fields we care about from a raw FDA record."""
    apps = r.get("application_number", [])
    app = apps[0] if isinstance(apps, list) and apps else str(apps)
    return {
        "application_number": app,
        "letter_date": r.get("letter_date", ""),
        "company_name": r.get("company_name", ""),
        "approval_status": r.get("approval_status", ""),
        "file_name": r.get("file_name", ""),
        "letter_type": r.get("letter_type", ""),
    }


def load_state(supabase):
    """Load all existing records from Supabase crl_state table."""
    print("Loading previous state from Supabase...")
    rows = []
    offset = 0
    batch_size = 1000
    while True:
        resp = (
            supabase.table("crl_state")
            .select("application_number, letter_date, approval_status")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows.extend(resp.data)
        if len(resp.data) < batch_size:
            break
        offset += batch_size
    print(f"  Loaded {len(rows)} existing records")
    return rows


def diff_records(fda_records, existing_rows):
    """
    Compare FDA data against stored state.
    Returns (new_crls, status_changes, all_parsed).
    """
    # Build lookup from existing: key → approval_status
    existing = {}
    for row in existing_rows:
        key = f"{row['application_number']}|{row['letter_date']}"
        existing[key] = row["approval_status"]

    new_crls = []
    status_changes = []
    all_parsed = []

    for r in fda_records:
        parsed = parse_record(r)
        all_parsed.append(parsed)
        key = f"{parsed['application_number']}|{parsed['letter_date']}"

        if key not in existing:
            # Brand new record
            new_crls.append(parsed)
        elif existing[key] != parsed["approval_status"]:
            # Status changed
            status_changes.append({
                **parsed,
                "old_status": existing[key],
                "new_status": parsed["approval_status"],
            })

    return new_crls, status_changes, all_parsed


def send_alert(new_crls, status_changes):
    """POST alert payload to n8n webhook with pre-formatted email."""
    # Build subject
    parts = []
    if new_crls:
        parts.append(f"{len(new_crls)} New CRL(s)")
    if status_changes:
        parts.append(f"{len(status_changes)} Status Change(s)")
    subject = f"FDA CRL Alert — {', '.join(parts)}"

    # Build HTML body
    body = "<h2>FDA CRL Alert</h2>"

    if new_crls:
        body += "<h3>New Complete Response Letters</h3>"
        for c in new_crls:
            pdf_url = f"{PDF_BASE_URL}/{c['file_name']}" if c["file_name"] else ""
            body += f"<p>"
            body += f"<b>{c['application_number']}</b> — {c['company_name']}<br/>"
            body += f"Date: {c['letter_date']}<br/>"
            body += f"Status: {c['approval_status']}<br/>"
            if pdf_url:
                body += f'<a href="{pdf_url}">View PDF</a>'
            body += "</p>"

    if status_changes:
        body += "<h3>Status Changes</h3>"
        for c in status_changes:
            body += f"<p>"
            body += f"<b>{c['application_number']}</b> — {c['company_name']}<br/>"
            body += f"Date: {c['letter_date']}<br/>"
            body += f"{c['old_status']} → {c['new_status']}"
            body += "</p>"

    payload = {
        "email_subject": subject,
        "email_body": body,
    }

    print(f"\nSending alert to n8n...")
    print(f"  Subject: {subject}")

    if N8N_WEBHOOK_URL:
        resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=30)
        print(f"  n8n response: {resp.status_code}")
    else:
        print("  N8N_WEBHOOK_URL not set, skipping POST")


def upsert_state(supabase, all_parsed):
    """Upsert all current records into Supabase."""
    # Deduplicate — FDA has duplicate app_number+letter_date combos
    seen = {}
    for rec in all_parsed:
        key = f"{rec['application_number']}|{rec['letter_date']}"
        seen[key] = rec  # last one wins
    deduped = list(seen.values())

    print(f"\nUpserting {len(deduped)} unique records to Supabase...")
    batch_size = 500
    for i in range(0, len(deduped), batch_size):
        batch = deduped[i : i + batch_size]
        supabase.table("crl_state").upsert(
            batch, on_conflict="application_number,letter_date"
        ).execute()
    print("  Done.")


def main():
    print("\n=== FDA CRL Scanner ===\n")

    # 1. Fetch from FDA
    fda_records = fetch_all_crls()
    if not fda_records:
        print("No records from FDA. Exiting.")
        return

    # 2. Connect to Supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set.")
        return
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 3. Load existing state
    existing_rows = load_state(supabase)

    # 4. Diff
    new_crls, status_changes, all_parsed = diff_records(fda_records, existing_rows)

    is_first_run = len(existing_rows) == 0

    print(f"\n--- Results ---")
    print(f"  New CRLs:        {len(new_crls)}")
    print(f"  Status changes:  {len(status_changes)}")
    print(f"  First run:       {is_first_run}")

    # 5. Alert (skip on first run to avoid 418 false alerts)
    if not is_first_run and (new_crls or status_changes):
        send_alert(new_crls, status_changes)
    elif is_first_run:
        print("\n  First run — seeding database, no alerts sent.")
    else:
        print("\n  No changes detected.")

    # 6. Upsert all records
    upsert_state(supabase, all_parsed)

    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()
