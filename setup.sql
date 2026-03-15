-- Run this in Supabase SQL Editor (one time setup)

CREATE TABLE IF NOT EXISTS crl_state (
  application_number  TEXT NOT NULL,
  letter_date         TEXT NOT NULL,
  company_name        TEXT,
  approval_status     TEXT,
  file_name           TEXT,
  letter_type         TEXT,
  first_seen_at       TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (application_number, letter_date)
);

-- Index for quick full-table scans
CREATE INDEX IF NOT EXISTS idx_crl_state_status ON crl_state (approval_status);
