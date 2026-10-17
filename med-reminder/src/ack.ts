import type { Config } from "./config";
import { getDose, resolveDose, snoozeDose } from "./db";
import { escapeHtml, isAckAction, verifyAck, type AckAction } from "./email";
import type { Env } from "./env";
import { DEFAULT_SNOOZE_MIN, doseLabel, snoozeText } from "./messages";

const LABELS: Record<AckAction, string> = { taken: "✅ Mark as taken", skip: "⏭ Skip this dose", snooze: `💤 Snooze ${DEFAULT_SNOOZE_MIN} min` };

function page(title: string, body: string, status = 200): Response {
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title></head>
<body style="font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;font-size:18px;line-height:1.5">${body}</body></html>`;
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

/**
 * Email ack links. GET only shows a confirm button: mail scanners prefetch links,
 * so acting on GET would mark doses taken that nobody took.
 */
export async function handleAck(req: Request, env: Env, cfg: Config, now: number): Promise<Response> {
  const params = req.method === "POST" ? new URLSearchParams(await req.text()) : new URL(req.url).searchParams;
  const doseId = Number(params.get("d"));
  const action = params.get("a") ?? "";
  const sig = params.get("s") ?? "";
  if (!Number.isInteger(doseId) || !isAckAction(action) || !(await verifyAck(env, doseId, action, sig))) {
    return page("Invalid link", "<p>This link is invalid or has been altered.</p>", 403);
  }
  const dose = await getDose(env.DB, doseId);
  if (!dose) return page("Not found", "<p>That dose no longer exists.</p>", 404);
  const label = escapeHtml(doseLabel(dose));

  if (dose.status !== "pending") {
    return page("Already logged", `<p>${label} was already logged as <b>${escapeHtml(dose.status)}</b>.</p>`);
  }

  if (req.method !== "POST") {
    return page(
      "Confirm",
      `<p>💊 <b>${label}</b></p>
<form method="post" action="/ack">
<input type="hidden" name="d" value="${doseId}"><input type="hidden" name="a" value="${escapeHtml(action)}"><input type="hidden" name="s" value="${escapeHtml(sig)}">
<button style="font-size:18px;padding:14px 22px;border-radius:10px;border:0;background:#15803d;color:#fff;font-weight:600">${LABELS[action]}</button>
</form>`,
    );
  }

  if (action === "snooze") {
    const until = now + DEFAULT_SNOOZE_MIN * 60_000;
    await snoozeDose(env.DB, doseId, until, now);
    return page("Snoozed", `<p>${escapeHtml(snoozeText(dose, until, cfg.timezone))}</p>`);
  }
  await resolveDose(env.DB, doseId, action === "taken" ? "taken" : "skipped", now, "email");
  return page("Logged", `<p>${action === "taken" ? "✅" : "⏭"} ${label} logged as <b>${action === "taken" ? "taken" : "skipped"}</b>. Reminders stopped.</p>`);
}
