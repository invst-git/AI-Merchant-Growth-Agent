export type DoseStatus = "pending" | "taken" | "skipped" | "missed" | "void";

export interface Dose {
  id: number;
  med_key: string;
  med_name: string;
  note: string | null;
  local_date: string;
  local_time: string;
  due_at: number;
  max_late_min: number;
  status: DoseStatus;
  next_send_at: number;
  attention_since: number;
  send_count: number;
  last_email_at: number | null;
  escalated_at: number | null;
  acked_at: number | null;
  acked_via: string | null;
}

export function cutoffAt(dose: Dose): number {
  return dose.due_at + dose.max_late_min * 60_000;
}

export async function getDose(db: D1Database, id: number): Promise<Dose | null> {
  return db.prepare("SELECT * FROM doses WHERE id = ?").bind(id).first<Dose>();
}

export async function dosesForDate(db: D1Database, date: string): Promise<Dose[]> {
  const { results } = await db
    .prepare("SELECT * FROM doses WHERE local_date = ? AND status != 'void' ORDER BY due_at, med_name")
    .bind(date)
    .all<Dose>();
  return results;
}

/** Pending doses due up to `until`, oldest first. */
export async function pendingDueBy(db: D1Database, until: number): Promise<Dose[]> {
  const { results } = await db
    .prepare("SELECT * FROM doses WHERE status = 'pending' AND due_at <= ? ORDER BY due_at, med_name")
    .bind(until)
    .all<Dose>();
  return results;
}

/** Moves a pending dose to a final status. Returns false if it was no longer pending. */
export async function resolveDose(
  db: D1Database,
  id: number,
  status: "taken" | "skipped" | "missed",
  now: number,
  via: string,
): Promise<boolean> {
  const res = await db
    .prepare("UPDATE doses SET status = ?, acked_at = ?, acked_via = ? WHERE id = ? AND status = 'pending'")
    .bind(status, now, via, id)
    .run();
  if (res.meta.changes === 1) await logEvent(db, now, id, status, via);
  return res.meta.changes === 1;
}

export async function snoozeDose(db: D1Database, id: number, until: number, now: number): Promise<boolean> {
  const res = await db
    .prepare("UPDATE doses SET next_send_at = ?, attention_since = ? WHERE id = ? AND status = 'pending'")
    .bind(until, until, id)
    .run();
  if (res.meta.changes === 1) await logEvent(db, now, id, "snooze", new Date(until).toISOString());
  return res.meta.changes === 1;
}

export async function kvGet(db: D1Database, key: string): Promise<string | null> {
  const row = await db.prepare("SELECT value FROM kv WHERE key = ?").bind(key).first<{ value: string }>();
  return row?.value ?? null;
}

export async function kvSet(db: D1Database, key: string, value: string): Promise<void> {
  await db
    .prepare("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value")
    .bind(key, value)
    .run();
}

export async function kvDelete(db: D1Database, key: string): Promise<void> {
  await db.prepare("DELETE FROM kv WHERE key = ?").bind(key).run();
}

export async function logEvent(db: D1Database, at: number, doseId: number | null, kind: string, detail?: string): Promise<void> {
  await db
    .prepare("INSERT INTO events (at, dose_id, kind, detail) VALUES (?, ?, ?, ?)")
    .bind(at, doseId, kind, detail ?? null)
    .run();
}
