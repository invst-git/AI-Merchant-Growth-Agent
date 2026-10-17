const encoder = new TextEncoder();

async function hmac(secret: string, message: string | ArrayBuffer): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return crypto.subtle.sign("HMAC", key, typeof message === "string" ? encoder.encode(message) : message);
}

function toHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function hmacHex(secret: string, message: string | ArrayBuffer): Promise<string> {
  return toHex(await hmac(secret, message));
}

/** Verifies Meta's X-Hub-Signature-256 header against the raw request body. */
export async function verifyMetaSignature(appSecret: string, rawBody: ArrayBuffer, header: string | null): Promise<boolean> {
  if (!header?.startsWith("sha256=")) return false;
  return timingSafeEqual(header.slice(7), await hmacHex(appSecret, rawBody));
}
