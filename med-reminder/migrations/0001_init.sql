-- One row per scheduled dose occurrence.
CREATE TABLE doses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  med_key TEXT NOT NULL,
  med_name TEXT NOT NULL,
  note TEXT,
  local_date TEXT NOT NULL,          -- YYYY-MM-DD in the configured timezone
  local_time TEXT NOT NULL,          -- HH:MM in the configured timezone
  due_at INTEGER NOT NULL,           -- epoch ms
  max_late_min INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | taken | skipped | missed | void
  next_send_at INTEGER NOT NULL,     -- when the next reminder goes out
  attention_since INTEGER NOT NULL,  -- start of the current unanswered stretch (reset by snooze)
  send_count INTEGER NOT NULL DEFAULT 0,
  last_email_at INTEGER,
  escalated_at INTEGER,
  acked_at INTEGER,
  acked_via TEXT,
  UNIQUE (med_key, local_date, local_time)
);
CREATE INDEX doses_pending ON doses (status, next_send_at);
CREATE INDEX doses_date ON doses (local_date);

-- Maps outgoing WhatsApp message ids to doses, so replying to a reminder acks that dose.
CREATE TABLE sent_messages (
  wamid TEXT PRIMARY KEY,
  dose_id INTEGER,
  recipient TEXT NOT NULL,
  sent_at INTEGER NOT NULL
);

-- Webhook deliveries can repeat; this makes inbound handling idempotent.
CREATE TABLE inbound_messages (
  wamid TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL
);

CREATE TABLE kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,
  dose_id INTEGER,
  kind TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX events_at ON events (at);
