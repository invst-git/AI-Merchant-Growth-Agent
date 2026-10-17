import type { Config } from "./config";
import { logEvent, type Dose } from "./db";
import { ackUrl, emailEnabled, escapeHtml, sendEmail } from "./email";
import type { Env } from "./env";
import { DEFAULT_SNOOZE_MIN, escalationText, reminderButtons, reminderText } from "./messages";
import { isWindowOpen, recordSent, WhatsApp } from "./whatsapp";

/** Sends a reminder over WhatsApp: buttons if the 24h window is open, otherwise the approved template. */
export async function sendWhatsAppReminder(env: Env, dose: Dose, now: number): Promise<void> {
  const wa = new WhatsApp(env);
  const to = env.PATIENT_WHATSAPP;
  const wamid = (await isWindowOpen(env.DB, to, now))
    ? await wa.sendButtons(to, reminderText(dose, now), reminderButtons(dose))
    : await wa.sendTemplate(
        to,
        env.WHATSAPP_TEMPLATE,
        [dose.med_name, dose.local_time],
        [`taken:${dose.id}`, `snooze:${dose.id}:${DEFAULT_SNOOZE_MIN}`],
      );
  await recordSent(env.DB, wamid, dose.id, to, now);
}

export async function sendEmailReminder(env: Env, dose: Dose, now: number): Promise<boolean> {
  if (!emailEnabled(env, env.PATIENT_EMAIL)) return false;
  const text = reminderText(dose, now).replace(/[*_]/g, "");
  const links = {
    taken: await ackUrl(env, dose.id, "taken"),
    snooze: await ackUrl(env, dose.id, "snooze"),
    skip: await ackUrl(env, dose.id, "skip"),
  };
  const button = (href: string, label: string, color: string) =>
    `<a href="${escapeHtml(href)}" style="display:inline-block;padding:12px 18px;margin:4px;border-radius:8px;background:${color};color:#fff;text-decoration:none;font-weight:600">${label}</a>`;
  const html = `<div style="font-family:system-ui,sans-serif;font-size:16px;line-height:1.5">
<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>
<p>${button(links.taken, "✅ Taken", "#15803d")}${button(links.snooze, `💤 Snooze ${DEFAULT_SNOOZE_MIN} min`, "#4b5563")}${button(links.skip, "⏭ Skip", "#9a3412")}</p>
<p style="color:#6b7280;font-size:13px">You can also reply "taken" on WhatsApp.</p></div>`;
  const plain = `${text}\n\nTaken: ${links.taken}\nSnooze ${DEFAULT_SNOOZE_MIN} min: ${links.snooze}\nSkip: ${links.skip}`;
  await sendEmail(env, env.PATIENT_EMAIL, `💊 ${dose.med_name}: due ${dose.local_time}`, plain, html);
  return true;
}

/**
 * Best-effort free-form message to the patient: WhatsApp when the window is open,
 * otherwise email. Returns the channel used, or null.
 */
export async function notifyPatient(env: Env, subject: string, text: string, now: number): Promise<"whatsapp" | "email" | null> {
  try {
    if (await isWindowOpen(env.DB, env.PATIENT_WHATSAPP, now)) {
      await new WhatsApp(env).sendText(env.PATIENT_WHATSAPP, text);
      return "whatsapp";
    }
  } catch (err) {
    await logEvent(env.DB, now, null, "whatsapp_error", String(err));
  }
  try {
    if (emailEnabled(env, env.PATIENT_EMAIL)) {
      const plain = text.replace(/[*_]/g, "");
      await sendEmail(env, env.PATIENT_EMAIL, subject, plain, `<pre style="font-family:system-ui,sans-serif;font-size:15px">${escapeHtml(plain)}</pre>`);
      return "email";
    }
  } catch (err) {
    await logEvent(env.DB, now, null, "email_error", String(err));
  }
  return null;
}

export async function notifyCaregiver(env: Env, dose: Dose, now: number, text: string): Promise<void> {
  const patientName = env.PATIENT_NAME || "Your contact";
  if (env.CAREGIVER_WHATSAPP) {
    try {
      const wa = new WhatsApp(env);
      let wamid: string | null = null;
      if (await isWindowOpen(env.DB, env.CAREGIVER_WHATSAPP, now)) {
        wamid = await wa.sendText(env.CAREGIVER_WHATSAPP, text);
      } else if (env.WHATSAPP_ESCALATION_TEMPLATE) {
        wamid = await wa.sendTemplate(env.CAREGIVER_WHATSAPP, env.WHATSAPP_ESCALATION_TEMPLATE, [patientName, dose.med_name, dose.local_time]);
      }
      if (wamid) await recordSent(env.DB, wamid, dose.id, env.CAREGIVER_WHATSAPP, now);
    } catch (err) {
      await logEvent(env.DB, now, dose.id, "whatsapp_error", `caregiver: ${err}`);
    }
  }
  if (emailEnabled(env, env.CAREGIVER_EMAIL)) {
    try {
      await sendEmail(env, env.CAREGIVER_EMAIL, `🔔 ${patientName}: ${dose.med_name} not confirmed`, text, `<p style="font-family:system-ui,sans-serif;font-size:16px">${escapeHtml(text)}</p>`);
    } catch (err) {
      await logEvent(env.DB, now, dose.id, "email_error", `caregiver: ${err}`);
    }
  }
}

export function caregiverConfigured(env: Env, cfg: Config): boolean {
  return cfg.escalateAfterMin !== null && Boolean(env.CAREGIVER_WHATSAPP || env.CAREGIVER_EMAIL);
}

export { escalationText };
