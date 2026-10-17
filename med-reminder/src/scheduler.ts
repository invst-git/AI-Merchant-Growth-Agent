import { medKey, type Config } from "./config";
import { cutoffAt, dosesForDate, kvGet, kvSet, logEvent, resolveDose, type Dose } from "./db";
import type { Env } from "./env";
import { digestText, escalationText, missedText } from "./messages";
import { caregiverConfigured, notifyCaregiver, notifyPatient, sendEmailReminder, sendWhatsAppReminder } from "./notify";
import { addDays, localParts, zonedToUtc } from "./time";

/** Doses created more than this long after their due time (first deploy, config edits) are voided, not nagged. */
const LATE_CREATION_GRACE_MS = 15 * 60_000;
/** Cron ticks drift by a few seconds; without slack a 10-minute nag would slip to 11 minutes. */
const TICK_SLACK_MS = 30_000;
const RETRY_AFTER_FAILURE_MS = 60_000;
const RETENTION_MS = 30 * 24 * 60 * 60_000;

export async function tick(env: Env, cfg: Config, now: number): Promise<void> {
  await ensureDoses(env.DB, cfg, now);
  await processDueDoses(env, cfg, now);
  await maybeSendDigest(env, cfg, now);
  await maybeCleanup(env.DB, cfg, now);
}

/** Materializes today's and tomorrow's doses from the config, and voids future doses no longer in it. */
export async function ensureDoses(db: D1Database, cfg: Config, now: number): Promise<void> {
  const today = localParts(now, cfg.timezone).date;
  const expected = new Set<string>();
  const statements: D1PreparedStatement[] = [];

  for (const date of [today, addDays(today, 1)]) {
    const weekday = localParts(zonedToUtc(date, "12:00", cfg.timezone), cfg.timezone).weekday;
    for (const med of cfg.meds) {
      if (med.days && !med.days.includes(weekday)) continue;
      const key = medKey(med.name);
      for (const time of med.times) {
        expected.add(`${key}|${date}|${time}`);
        const due = zonedToUtc(date, time, cfg.timezone);
        const status = due < now - LATE_CREATION_GRACE_MS ? "void" : "pending";
        statements.push(
          db
            .prepare(
              `INSERT INTO doses (med_key, med_name, note, local_date, local_time, due_at, max_late_min, status, next_send_at, attention_since)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?6, ?6)
               ON CONFLICT (med_key, local_date, local_time) DO UPDATE SET
                 med_name = excluded.med_name,
                 note = excluded.note,
                 max_late_min = excluded.max_late_min,
                 status = 'pending'
               WHERE (doses.status = 'pending' AND doses.due_at > ?9 AND (
                        doses.med_name != excluded.med_name OR doses.note IS NOT excluded.note OR doses.max_late_min != excluded.max_late_min))
                  OR (doses.status = 'void' AND excluded.status = 'pending')`,
            )
            .bind(key, med.name, med.note ?? null, date, time, due, med.maxLateMin ?? cfg.defaultMaxLateMin, status, now),
        );
      }
    }
  }
  if (statements.length > 0) await db.batch(statements);

  const { results: future } = await db
    .prepare("SELECT id, med_key, local_date, local_time FROM doses WHERE status = 'pending' AND due_at > ?")
    .bind(now)
    .all<Pick<Dose, "id" | "med_key" | "local_date" | "local_time">>();
  const removed = future.filter((d) => !expected.has(`${d.med_key}|${d.local_date}|${d.local_time}`));
  if (removed.length > 0) {
    await db.batch(removed.map((d) => db.prepare("UPDATE doses SET status = 'void' WHERE id = ? AND status = 'pending'").bind(d.id)));
  }
}

export async function processDueDoses(env: Env, cfg: Config, now: number): Promise<void> {
  const { results } = await env.DB
    .prepare(
      `SELECT * FROM doses WHERE status = 'pending' AND due_at <= ?1
       AND (next_send_at <= ?1 OR due_at + max_late_min * 60000 <= ?1) ORDER BY due_at`,
    )
    .bind(now)
    .all<Dose>();

  for (const dose of results) {
    try {
      if (now >= cutoffAt(dose)) await markMissed(env, cfg, dose, now);
      else await remind(env, cfg, dose, now);
    } catch (err) {
      // One dose failing must never stop the others from being reminded.
      await logEvent(env.DB, now, dose.id, "tick_error", String(err));
    }
  }
}

async function remind(env: Env, cfg: Config, dose: Dose, now: number): Promise<void> {
  const nagMs = cfg.nagIntervalMin * 60_000;
  // Claiming the send with a conditional update keeps overlapping ticks from double-sending.
  const claim = await env.DB
    .prepare("UPDATE doses SET next_send_at = ?, send_count = send_count + 1 WHERE id = ? AND status = 'pending' AND next_send_at <= ?")
    .bind(now + nagMs - TICK_SLACK_MS, dose.id, now)
    .run();
  if (claim.meta.changes !== 1) return;
  dose.send_count += 1;

  let whatsappOk = true;
  try {
    await sendWhatsAppReminder(env, dose, now);
    await logEvent(env.DB, now, dose.id, "reminded", `whatsapp #${dose.send_count}`);
  } catch (err) {
    whatsappOk = false;
    await logEvent(env.DB, now, dose.id, "whatsapp_error", String(err));
    await env.DB.prepare("UPDATE doses SET next_send_at = ? WHERE id = ?").bind(now + RETRY_AFTER_FAILURE_MS, dose.id).run();
  }

  const unansweredMin = (now - dose.attention_since) / 60_000;
  const emailDue = cfg.emailFallbackAfterMin !== null && unansweredMin >= cfg.emailFallbackAfterMin;
  const emailedRecently = dose.last_email_at !== null && now - dose.last_email_at < nagMs - TICK_SLACK_MS;
  if ((emailDue || !whatsappOk) && !emailedRecently) {
    try {
      if (await sendEmailReminder(env, dose, now)) {
        await env.DB.prepare("UPDATE doses SET last_email_at = ? WHERE id = ?").bind(now, dose.id).run();
        await logEvent(env.DB, now, dose.id, "reminded", "email");
      }
    } catch (err) {
      await logEvent(env.DB, now, dose.id, "email_error", String(err));
    }
  }

  if (cfg.escalateAfterMin !== null && dose.escalated_at === null && unansweredMin >= cfg.escalateAfterMin && caregiverConfigured(env, cfg)) {
    const claimed = await env.DB
      .prepare("UPDATE doses SET escalated_at = ? WHERE id = ? AND escalated_at IS NULL")
      .bind(now, dose.id)
      .run();
    if (claimed.meta.changes === 1) {
      await notifyCaregiver(env, dose, now, escalationText(env.PATIENT_NAME || "Your contact", dose, now));
      await logEvent(env.DB, now, dose.id, "escalated");
    }
  }
}

async function markMissed(env: Env, cfg: Config, dose: Dose, now: number): Promise<void> {
  if (!(await resolveDose(env.DB, dose.id, "missed", now, "auto"))) return;
  await notifyPatient(env, `❌ Missed: ${dose.med_name} (${dose.local_time})`, missedText(dose), now);
  if (caregiverConfigured(env, cfg)) {
    await notifyCaregiver(env, dose, now, `❌ ${env.PATIENT_NAME || "Your contact"} missed ${dose.med_name} (due ${dose.local_time}).`);
  }
}

async function maybeSendDigest(env: Env, cfg: Config, now: number): Promise<void> {
  if (cfg.digestTime === null) return;
  const local = localParts(now, cfg.timezone);
  if (local.time < cfg.digestTime) return;
  const key = `digest:${local.date}`;
  if (await kvGet(env.DB, key)) return;
  await kvSet(env.DB, key, String(now));
  const doses = await dosesForDate(env.DB, local.date);
  if (doses.length === 0) return;
  await notifyPatient(env, `📋 Medication summary for ${local.date}`, digestText(local.date, doses, now, cfg.timezone), now);
}

async function maybeCleanup(db: D1Database, cfg: Config, now: number): Promise<void> {
  const today = localParts(now, cfg.timezone).date;
  if ((await kvGet(db, "cleanup")) === today) return;
  const cutoff = now - RETENTION_MS;
  await db.batch([
    db.prepare("DELETE FROM sent_messages WHERE sent_at < ?").bind(cutoff),
    db.prepare("DELETE FROM inbound_messages WHERE received_at < ?").bind(cutoff),
    db.prepare("DELETE FROM kv WHERE key LIKE 'digest:%' AND CAST(value AS INTEGER) < ?").bind(cutoff),
  ]);
  await kvSet(db, "cleanup", today);
}
