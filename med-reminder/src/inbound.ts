import { parseButtonId, parseText, type Command } from "./commands";
import type { Config } from "./config";
import { dosesForDate, getDose, logEvent, pendingDueBy, resolveDose, snoozeDose, type Dose } from "./db";
import { digits, type Env } from "./env";
import { doseLabel, HELP_TEXT, snoozeText, statusText } from "./messages";
import { localParts } from "./time";
import { closeWindow, recordInbound, WhatsApp } from "./whatsapp";

/** "taken" with nothing due yet logs the next dose if it's this close (taken early). */
const EARLY_WINDOW_MS = 60 * 60_000;
/** WhatsApp error: more than 24h since the user last messaged; only templates are allowed. */
const REENGAGEMENT_ERROR = 131047;

export interface InboundMessage {
  id: string;
  from: string;
  type: string;
  text?: { body: string };
  interactive?: { type: string; button_reply?: { id: string; title: string } };
  button?: { payload?: string; text?: string };
  context?: { id?: string };
}

export interface StatusUpdate {
  id: string;
  status: string;
  recipient_id: string;
  errors?: { code?: number; title?: string; message?: string }[];
}

export interface WebhookPayload {
  entry?: { changes?: { value?: { messages?: InboundMessage[]; statuses?: StatusUpdate[] } }[] }[];
}

export async function handleWebhook(env: Env, cfg: Config, payload: WebhookPayload, now: number): Promise<void> {
  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      for (const message of change.value?.messages ?? []) await handleMessage(env, cfg, message, now);
      for (const status of change.value?.statuses ?? []) await handleStatus(env, status, now);
    }
  }
}

export function commandFromMessage(m: InboundMessage): Command {
  const fromButton = m.interactive?.button_reply?.id ?? m.button?.payload;
  if (fromButton) {
    const cmd = parseButtonId(fromButton);
    if (cmd) return cmd;
  }
  return parseText(m.text?.body ?? m.button?.text ?? m.interactive?.button_reply?.title ?? "");
}

async function handleMessage(env: Env, cfg: Config, m: InboundMessage, now: number): Promise<void> {
  const fresh = await env.DB
    .prepare("INSERT OR IGNORE INTO inbound_messages (wamid, received_at) VALUES (?, ?)")
    .bind(m.id, now)
    .run();
  if (fresh.meta.changes !== 1) return; // redelivery

  const from = digits(m.from);
  const isPatient = from === digits(env.PATIENT_WHATSAPP);
  const isCaregiver = Boolean(env.CAREGIVER_WHATSAPP) && from === digits(env.CAREGIVER_WHATSAPP);
  if (!isPatient && !isCaregiver) {
    await logEvent(env.DB, now, null, "ignored_sender", from);
    return;
  }
  await recordInbound(env.DB, from, now);

  const cmd = commandFromMessage(m);
  let reply: string;
  if (isPatient) {
    const contextDoseId = m.context?.id ? await doseIdForMessage(env.DB, m.context.id) : null;
    reply = await runCommand(env, cfg, cmd, contextDoseId, now);
  } else {
    reply =
      cmd.kind === "status"
        ? await todayStatus(env, cfg, now)
        : `👋 You're set up as a caregiver: you'll get an alert if ${env.PATIENT_NAME || "they"} don't confirm a dose. Send *today* to see today's doses.`;
  }
  await new WhatsApp(env).sendText(from, reply);
}

async function doseIdForMessage(db: D1Database, wamid: string): Promise<number | null> {
  const row = await db.prepare("SELECT dose_id FROM sent_messages WHERE wamid = ?").bind(wamid).first<{ dose_id: number | null }>();
  return row?.dose_id ?? null;
}

async function todayStatus(env: Env, cfg: Config, now: number): Promise<string> {
  const date = localParts(now, cfg.timezone).date;
  return statusText(`Today (${date})`, await dosesForDate(env.DB, date), now, cfg.timezone);
}

export async function runCommand(env: Env, cfg: Config, cmd: Command, contextDoseId: number | null, now: number): Promise<string> {
  if (cmd.kind === "help") {
    const pending = await pendingDueBy(env.DB, now);
    return pending.length > 0 ? `${HELP_TEXT}\n\n⏳ Waiting for you: ${pending.map(doseLabel).join(", ")}` : HELP_TEXT;
  }
  if (cmd.kind === "status") return todayStatus(env, cfg, now);

  const targets = await resolveTargets(env.DB, cmd, contextDoseId, now);
  if (targets.length === 0) {
    const next = (await pendingDueBy(env.DB, now + 24 * 60 * 60_000))[0];
    const nextLine = next ? ` Next up: ${doseLabel(next)}.` : "";
    const what = "filter" in cmd && cmd.filter ? ` matching "${cmd.filter}"` : "";
    return `👍 Nothing${what} is waiting for you right now.${nextLine}`;
  }

  const lines: string[] = [];
  for (const dose of targets) {
    if (dose.status !== "pending") {
      lines.push(`ℹ️ ${doseLabel(dose)} was already logged as ${dose.status}.`);
    } else if (cmd.kind === "snooze") {
      const until = now + cmd.minutes * 60_000;
      await snoozeDose(env.DB, dose.id, until, now);
      lines.push(snoozeText(dose, until, cfg.timezone));
    } else {
      const status = cmd.kind === "taken" ? "taken" : "skipped";
      await resolveDose(env.DB, dose.id, status, now, "whatsapp");
      const early = dose.due_at > now ? " (early)" : "";
      lines.push(status === "taken" ? `✅ ${doseLabel(dose)}: logged as taken${early}.` : `⏭ ${doseLabel(dose)}: skipped.`);
    }
  }

  const handled = new Set(targets.map((d) => d.id));
  const stillWaiting = (await pendingDueBy(env.DB, now)).filter((d) => !handled.has(d.id));
  if (stillWaiting.length > 0) lines.push(`⏳ Still waiting: ${stillWaiting.map(doseLabel).join(", ")}`);
  return lines.join("\n");
}

async function resolveTargets(
  db: D1Database,
  cmd: Extract<Command, { kind: "taken" | "skip" | "snooze" }>,
  contextDoseId: number | null,
  now: number,
): Promise<Dose[]> {
  const explicitId = cmd.doseId ?? (cmd.filter ? null : contextDoseId);
  if (explicitId) {
    const dose = await getDose(db, explicitId);
    return dose && dose.status !== "void" ? [dose] : [];
  }

  const early = cmd.kind === "snooze" ? 0 : EARLY_WINDOW_MS;
  let candidates = await pendingDueBy(db, now + early);
  if (cmd.filter) {
    const f = cmd.filter;
    candidates = candidates.filter((d) => d.med_name.toLowerCase().includes(f) || d.med_key.includes(f.replace(/\s+/g, "-")));
  }
  const due = candidates.filter((d) => d.due_at <= now);
  if (due.length > 0) return due;
  // Nothing due: allow logging the very next dose early.
  return candidates.slice(0, 1);
}

async function handleStatus(env: Env, s: StatusUpdate, now: number): Promise<void> {
  if (s.status !== "failed") return;
  const error = s.errors?.[0];
  await logEvent(env.DB, now, null, "delivery_failed", `${s.recipient_id}: ${error?.code ?? "?"} ${error?.title ?? ""}`.trim());
  if (error?.code !== REENGAGEMENT_ERROR) return;

  // Our window bookkeeping was wrong: fall back to the template and resend on the next tick.
  await closeWindow(env.DB, s.recipient_id);
  const doseId = await doseIdForMessage(env.DB, s.id);
  if (doseId) {
    await env.DB.prepare("UPDATE doses SET next_send_at = ? WHERE id = ? AND status = 'pending'").bind(now, doseId).run();
  }
}
