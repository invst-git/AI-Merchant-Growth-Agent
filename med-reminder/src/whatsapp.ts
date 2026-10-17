import { kvDelete, kvGet, kvSet } from "./db";
import { digits, type Env } from "./env";

/** WhatsApp only allows free-form messages within 24h of the user's last message. Keep a margin. */
const WINDOW_MS = 23.5 * 60 * 60_000;

export interface Button {
  id: string;
  title: string; // max 20 chars
}

export class WhatsAppError extends Error {
  constructor(
    message: string,
    readonly code?: number,
  ) {
    super(message);
  }
}

export class WhatsApp {
  constructor(private readonly env: Env) {}

  sendText(to: string, text: string): Promise<string> {
    return this.post({ to: digits(to), type: "text", text: { body: text, preview_url: false } });
  }

  sendButtons(to: string, text: string, buttons: Button[]): Promise<string> {
    return this.post({
      to: digits(to),
      type: "interactive",
      interactive: {
        type: "button",
        body: { text },
        action: { buttons: buttons.map((b) => ({ type: "reply", reply: { id: b.id, title: b.title } })) },
      },
    });
  }

  /** Sends an approved template. `quickReplyPayloads[i]` becomes the payload of the template's i-th quick-reply button. */
  sendTemplate(to: string, name: string, bodyParams: string[], quickReplyPayloads: string[] = []): Promise<string> {
    const components: unknown[] = [];
    if (bodyParams.length > 0) {
      components.push({ type: "body", parameters: bodyParams.map((text) => ({ type: "text", text })) });
    }
    quickReplyPayloads.forEach((payload, i) => {
      components.push({ type: "button", sub_type: "quick_reply", index: String(i), parameters: [{ type: "payload", payload }] });
    });
    return this.post({
      to: digits(to),
      type: "template",
      template: { name, language: { code: this.env.WHATSAPP_TEMPLATE_LANG }, components },
    });
  }

  private async post(message: Record<string, unknown>): Promise<string> {
    const res = await fetch(`${this.env.GRAPH_API_BASE}/${this.env.WHATSAPP_PHONE_NUMBER_ID}/messages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.env.WHATSAPP_TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify({ messaging_product: "whatsapp", recipient_type: "individual", ...message }),
    });
    const json = (await res.json().catch(() => ({}))) as {
      messages?: { id: string }[];
      error?: { message?: string; code?: number };
    };
    if (!res.ok) {
      throw new WhatsAppError(`WhatsApp API ${res.status}: ${json.error?.message ?? "unknown error"}`, json.error?.code);
    }
    const id = json.messages?.[0]?.id;
    if (!id) throw new WhatsAppError("WhatsApp API returned no message id");
    return id;
  }
}

function windowKey(phone: string): string {
  return `last_inbound:${digits(phone)}`;
}

export async function recordInbound(db: D1Database, phone: string, now: number): Promise<void> {
  await kvSet(db, windowKey(phone), String(now));
}

export async function closeWindow(db: D1Database, phone: string): Promise<void> {
  await kvDelete(db, windowKey(phone));
}

export async function isWindowOpen(db: D1Database, phone: string, now: number): Promise<boolean> {
  const last = Number(await kvGet(db, windowKey(phone)));
  return last > 0 && now - last < WINDOW_MS;
}

export async function recordSent(db: D1Database, wamid: string, doseId: number | null, recipient: string, now: number): Promise<void> {
  await db
    .prepare("INSERT OR IGNORE INTO sent_messages (wamid, dose_id, recipient, sent_at) VALUES (?, ?, ?, ?)")
    .bind(wamid, doseId, digits(recipient), now)
    .run();
}
