import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { vi } from "vitest";
import type { Config } from "../src/config";
import { hmacHex } from "../src/crypto";
import type { Env } from "../src/env";

type Value = string | number | null;

/** Minimal D1Database backed by an in-memory SQLite with the real migration applied. */
class FakeStatement {
  constructor(
    private readonly db: DatabaseSync,
    readonly sql: string,
    private readonly params: Value[] = [],
  ) {}
  bind(...params: unknown[]): FakeStatement {
    return new FakeStatement(this.db, this.sql, params.map((p) => (p === undefined ? null : (p as Value))));
  }
  async first<T>(): Promise<T | null> {
    return (this.db.prepare(this.sql).get(...this.params) as T | undefined) ?? null;
  }
  async all<T>() {
    return { results: this.db.prepare(this.sql).all(...this.params) as T[], success: true, meta: {} };
  }
  async run() {
    return this.runSync();
  }
  runSync() {
    const r = this.db.prepare(this.sql).run(...this.params);
    return { success: true, results: [], meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } };
  }
}

export class FakeD1 {
  readonly sqlite = new DatabaseSync(":memory:");
  constructor() {
    this.sqlite.exec(readFileSync(new URL("../migrations/0001_init.sql", import.meta.url), "utf8"));
  }
  prepare(sql: string) {
    return new FakeStatement(this.sqlite, sql);
  }
  async batch(statements: FakeStatement[]) {
    this.sqlite.exec("BEGIN");
    try {
      // Synchronous on purpose: like D1, a batch must not interleave with other queries.
      const out = statements.map((s) => s.runSync());
      this.sqlite.exec("COMMIT");
      return out;
    } catch (err) {
      this.sqlite.exec("ROLLBACK");
      throw err;
    }
  }
  rows<T = Record<string, unknown>>(sql: string, ...params: Value[]): T[] {
    return this.sqlite.prepare(sql).all(...params) as T[];
  }
}

export const PATIENT = "919800000001";
export const CAREGIVER = "919800000002";

export function makeEnv(overrides: Partial<Env> = {}): Env & { DB: FakeD1 & D1Database } {
  return {
    DB: new FakeD1() as unknown as FakeD1 & D1Database,
    WHATSAPP_TOKEN: "token",
    WHATSAPP_PHONE_NUMBER_ID: "12345",
    WHATSAPP_APP_SECRET: "app-secret",
    WHATSAPP_VERIFY_TOKEN: "verify-me",
    WHATSAPP_TEMPLATE: "med_reminder",
    WHATSAPP_TEMPLATE_LANG: "en",
    WHATSAPP_ESCALATION_TEMPLATE: "med_escalation",
    GRAPH_API_BASE: "https://graph.test/v23.0",
    PATIENT_WHATSAPP: `+${PATIENT}`,
    PATIENT_NAME: "Asha",
    PATIENT_EMAIL: "patient@example.com",
    CAREGIVER_WHATSAPP: CAREGIVER,
    CAREGIVER_EMAIL: "carer@example.com",
    RESEND_API_KEY: "re_key",
    EMAIL_FROM: "Med Reminder <onboarding@resend.dev>",
    ACK_SECRET: "ack-secret",
    PUBLIC_URL: "https://med.example.workers.dev",
    ...overrides,
  } as Env & { DB: FakeD1 & D1Database };
}

export const TZ = "Asia/Kolkata";

export function makeConfig(overrides: Partial<Config> = {}): Config {
  return {
    timezone: TZ,
    nagIntervalMin: 10,
    emailFallbackAfterMin: 30,
    escalateAfterMin: 90,
    defaultMaxLateMin: 240,
    digestTime: null,
    meds: [{ name: "Metformin 500mg", times: ["08:00", "20:00"], note: "with food" }],
    ...overrides,
  };
}

/** Epoch ms for a wall-clock time in Asia/Kolkata (UTC+5:30, no DST). 2026-10-19 is a Monday. */
export function ist(time: string, date = "2026-10-19"): number {
  return Date.parse(`${date}T${time}:00+05:30`);
}

export interface SentWhatsApp {
  to: string;
  type: string;
  text?: string;
  template?: string;
  params?: string[];
  payloads?: string[];
  buttons?: string[];
}

/** Stubs fetch: records WhatsApp sends, emails and healthcheck pings. */
export function mockApis() {
  const whatsapp: SentWhatsApp[] = [];
  const emails: { to: string; subject: string; text: string; html: string }[] = [];
  const pings: string[] = [];
  let failWhatsApp: { status: number; code: number; message: string } | null = null;
  let n = 0;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith("https://graph.test/")) {
      if (failWhatsApp) {
        return Response.json({ error: { code: failWhatsApp.code, message: failWhatsApp.message } }, { status: failWhatsApp.status });
      }
      const body = JSON.parse(String(init?.body));
      const msg: SentWhatsApp = { to: body.to, type: body.type };
      if (body.type === "text") msg.text = body.text.body;
      if (body.type === "interactive") {
        msg.text = body.interactive.body.text;
        msg.buttons = body.interactive.action.buttons.map((b: { reply: { id: string } }) => b.reply.id);
      }
      if (body.type === "template") {
        msg.template = body.template.name;
        for (const c of body.template.components) {
          if (c.type === "body") msg.params = c.parameters.map((p: { text: string }) => p.text);
          if (c.type === "button") (msg.payloads ??= []).push(c.parameters[0].payload);
        }
      }
      whatsapp.push(msg);
      return Response.json({ messages: [{ id: `wamid.${++n}` }] });
    }
    if (url === "https://api.resend.com/emails") {
      const body = JSON.parse(String(init?.body));
      emails.push({ to: body.to[0], subject: body.subject, text: body.text, html: body.html });
      return Response.json({ id: `email-${emails.length}` });
    }
    pings.push(url);
    return new Response("ok");
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    whatsapp,
    emails,
    pings,
    failWhatsAppWith(err: typeof failWhatsApp) {
      failWhatsApp = err;
    },
    clear() {
      whatsapp.length = 0;
      emails.length = 0;
      pings.length = 0;
    },
    lastWamid: () => `wamid.${n}`,
  };
}

let inboundCounter = 0;

export function textMessage(body: string, extra: Record<string, unknown> = {}, from = PATIENT) {
  return { id: `in.${++inboundCounter}`, from, type: "text", text: { body }, ...extra };
}

export function buttonReply(id: string, from = PATIENT) {
  return { id: `in.${++inboundCounter}`, from, type: "interactive", interactive: { type: "button_reply", button_reply: { id, title: "x" } } };
}

export function webhookBody(messages: unknown[] = [], statuses: unknown[] = []) {
  return { object: "whatsapp_business_account", entry: [{ changes: [{ field: "messages", value: { messages, statuses } }] }] };
}

export async function signedWebhook(env: Env, payload: unknown): Promise<Request> {
  const body = JSON.stringify(payload);
  const sig = await hmacHex(env.WHATSAPP_APP_SECRET, new TextEncoder().encode(body).buffer as ArrayBuffer);
  return new Request("https://med.example.workers.dev/webhook", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Signature-256": `sha256=${sig}` },
    body,
  });
}
