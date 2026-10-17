import { hmacHex, timingSafeEqual } from "./crypto";
import type { Env } from "./env";

export type AckAction = "taken" | "skip" | "snooze";

export function emailEnabled(env: Env, to: string | undefined): to is string {
  return Boolean(env.RESEND_API_KEY && env.EMAIL_FROM && to);
}

export async function sendEmail(env: Env, to: string, subject: string, text: string, html: string): Promise<void> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: env.EMAIL_FROM, to: [to], subject, text, html }),
  });
  if (!res.ok) throw new Error(`Resend API ${res.status}: ${await res.text().catch(() => "")}`);
}

async function ackSignature(env: Env, doseId: number, action: AckAction): Promise<string> {
  return (await hmacHex(env.ACK_SECRET, `ack:${doseId}:${action}`)).slice(0, 32);
}

export async function ackUrl(env: Env, doseId: number, action: AckAction): Promise<string> {
  const url = new URL("/ack", env.PUBLIC_URL);
  url.searchParams.set("d", String(doseId));
  url.searchParams.set("a", action);
  url.searchParams.set("s", await ackSignature(env, doseId, action));
  return url.toString();
}

export function isAckAction(action: string): action is AckAction {
  return action === "taken" || action === "skip" || action === "snooze";
}

export async function verifyAck(env: Env, doseId: number, action: AckAction, signature: string): Promise<boolean> {
  return timingSafeEqual(signature, await ackSignature(env, doseId, action));
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
