import { config } from "../meds.config";
import { handleAck } from "./ack";
import { validateConfig, type Config } from "./config";
import { verifyMetaSignature } from "./crypto";
import { logEvent } from "./db";
import type { Env } from "./env";
import { handleWebhook, type WebhookPayload } from "./inbound";
import { tick } from "./scheduler";

export async function route(req: Request, env: Env, cfg: Config, now: number): Promise<Response> {
  const url = new URL(req.url);

  if (url.pathname === "/webhook" && req.method === "GET") {
    // Meta's one-time webhook verification handshake.
    const ok = url.searchParams.get("hub.mode") === "subscribe" && url.searchParams.get("hub.verify_token") === env.WHATSAPP_VERIFY_TOKEN;
    return ok ? new Response(url.searchParams.get("hub.challenge") ?? "") : new Response("forbidden", { status: 403 });
  }

  if (url.pathname === "/webhook" && req.method === "POST") {
    const raw = await req.arrayBuffer();
    if (!(await verifyMetaSignature(env.WHATSAPP_APP_SECRET, raw, req.headers.get("X-Hub-Signature-256")))) {
      return new Response("bad signature", { status: 401 });
    }
    try {
      await handleWebhook(env, cfg, JSON.parse(new TextDecoder().decode(raw)) as WebhookPayload, now);
    } catch (err) {
      // Still answer 200: Meta retries failed deliveries for days, which would replay the same error.
      console.error("webhook error", err);
      await logEvent(env.DB, now, null, "webhook_error", String(err)).catch(() => {});
    }
    return new Response("ok");
  }

  if (url.pathname === "/ack" && (req.method === "GET" || req.method === "POST")) {
    return handleAck(req, env, cfg, now);
  }

  if (url.pathname === "/" && req.method === "GET") return new Response("med-reminder is running");
  return new Response("not found", { status: 404 });
}

export async function runScheduled(env: Env, cfg: Config, now: number): Promise<void> {
  try {
    const errors = validateConfig(cfg);
    if (errors.length > 0) throw new Error(`meds.config.ts is invalid:\n${errors.join("\n")}`);
    await tick(env, cfg, now);
    if (env.HEALTHCHECK_URL) await fetch(env.HEALTHCHECK_URL).catch(() => {});
  } catch (err) {
    console.error("tick failed", err);
    if (env.HEALTHCHECK_URL) {
      await fetch(`${env.HEALTHCHECK_URL.replace(/\/$/, "")}/fail`, { method: "POST", body: String(err) }).catch(() => {});
    }
    throw err;
  }
}

export default {
  fetch(req, env, _ctx) {
    return route(req, env, config, Date.now());
  },
  scheduled(_controller, env, ctx) {
    ctx.waitUntil(runScheduled(env, config, Date.now()));
  },
} satisfies ExportedHandler<Env>;
