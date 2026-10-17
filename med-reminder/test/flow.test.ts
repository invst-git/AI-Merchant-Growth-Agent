import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dose } from "../src/db";
import { ackUrl } from "../src/email";
import { route, runScheduled } from "../src/index";
import { tick } from "../src/scheduler";
import { recordInbound } from "../src/whatsapp";
import {
  buttonReply,
  CAREGIVER,
  ist,
  makeConfig,
  makeEnv,
  mockApis,
  PATIENT,
  signedWebhook,
  textMessage,
  webhookBody,
} from "./helpers";

const MIN = 60_000;

let env: ReturnType<typeof makeEnv>;
let api: ReturnType<typeof mockApis>;
let cfg = makeConfig();

beforeEach(() => {
  env = makeEnv();
  api = mockApis();
  cfg = makeConfig();
});
afterEach(() => vi.unstubAllGlobals());

const doses = () => env.DB.rows<Dose>("SELECT * FROM doses ORDER BY due_at, med_name");
const dose = (time: string, date = "2026-10-19") =>
  env.DB.rows<Dose>("SELECT * FROM doses WHERE local_time = ? AND local_date = ?", time, date)[0]!;

/** Runs the cron every minute from `from` to `to` inclusive, like Cloudflare would (with a little jitter). */
async function runMinutes(from: number, to: number) {
  for (let t = from; t <= to; t += MIN) await tick(env, cfg, t + 2_000);
}

async function webhook(...messages: unknown[]) {
  const res = await route(await signedWebhook(env, webhookBody(messages)), env, cfg, lastNow);
  expect(res.status).toBe(200);
}
let lastNow = 0;
async function at(time: number, fn: () => Promise<void>) {
  lastNow = time;
  await fn();
}

describe("dose generation", () => {
  it("creates today's and tomorrow's doses, respecting weekdays", async () => {
    cfg = makeConfig({ meds: [{ name: "Metformin", times: ["08:00", "20:00"] }, { name: "Vitamin D", times: ["09:00"], days: ["tue"] }] });
    await tick(env, cfg, ist("00:00"));
    expect(doses().map((d) => `${d.local_date} ${d.local_time} ${d.med_name} ${d.status}`)).toEqual([
      "2026-10-19 08:00 Metformin pending",
      "2026-10-19 20:00 Metformin pending",
      "2026-10-20 08:00 Metformin pending",
      "2026-10-20 09:00 Vitamin D pending",
      "2026-10-20 20:00 Metformin pending",
    ]);
    expect(dose("08:00").due_at).toBe(Date.parse("2026-10-19T02:30:00Z"));
  });

  it("voids doses that were already long past when first created (e.g. first deploy at noon)", async () => {
    await tick(env, cfg, ist("12:00"));
    expect(dose("08:00").status).toBe("void");
    expect(dose("20:00").status).toBe("pending");
    expect(api.whatsapp).toHaveLength(0);
  });

  it("is idempotent across ticks", async () => {
    await tick(env, cfg, ist("00:00"));
    await tick(env, cfg, ist("00:01"));
    expect(doses()).toHaveLength(4);
  });

  it("voids future doses removed from the config and picks up note changes", async () => {
    await tick(env, cfg, ist("00:00"));
    cfg = makeConfig({ meds: [{ name: "Metformin 500mg", times: ["08:00"], note: "after breakfast" }] });
    await tick(env, cfg, ist("00:01"));
    expect(dose("20:00").status).toBe("void");
    expect(dose("08:00").note).toBe("after breakfast");
    // Adding it back revives it.
    cfg = makeConfig();
    await tick(env, cfg, ist("00:02"));
    expect(dose("20:00").status).toBe("pending");
  });
});

describe("reminders", () => {
  it("uses the template when the 24h window is closed, buttons when open", async () => {
    await runMinutes(ist("07:58"), ist("08:00"));
    expect(api.whatsapp).toHaveLength(1);
    expect(api.whatsapp[0]).toMatchObject({
      to: PATIENT,
      type: "template",
      template: "med_reminder",
      params: ["Metformin 500mg", "08:00"],
      payloads: [`taken:${dose("08:00").id}`, `snooze:${dose("08:00").id}:30`],
    });

    await recordInbound(env.DB, PATIENT, ist("08:05"));
    await runMinutes(ist("08:01"), ist("08:10"));
    expect(api.whatsapp).toHaveLength(2);
    expect(api.whatsapp[1]!.type).toBe("interactive");
    expect(api.whatsapp[1]!.text).toContain("Metformin 500mg");
    expect(api.whatsapp[1]!.text).toContain("10 min late · reminder #2");
    expect(api.whatsapp[1]!.buttons).toEqual([`taken:${dose("08:00").id}`, `snooze:${dose("08:00").id}:30`, `skip:${dose("08:00").id}`]);
  });

  it("repeats exactly every 10 minutes until acknowledged", async () => {
    await recordInbound(env.DB, PATIENT, ist("07:00"));
    await runMinutes(ist("07:59"), ist("08:25"));
    const sentAt = env.DB.rows<{ at: number }>("SELECT at FROM events WHERE kind = 'reminded' AND detail LIKE 'whatsapp%'").map(
      (e) => Math.round((e.at - ist("08:00")) / MIN),
    );
    expect(sentAt).toEqual([0, 10, 20]);

    await at(ist("08:26"), () => webhook(buttonReply(`taken:${dose("08:00").id}`)));
    expect(dose("08:00")).toMatchObject({ status: "taken", acked_via: "whatsapp" });
    expect(api.whatsapp.at(-1)!.text).toBe("✅ Metformin 500mg (08:00): logged as taken.");

    api.clear();
    await runMinutes(ist("08:27"), ist("09:30"));
    expect(api.whatsapp).toHaveLength(0);
  });

  it("does not double-send when ticks overlap", async () => {
    await Promise.all([tick(env, cfg, ist("08:00")), tick(env, cfg, ist("08:00"))]);
    expect(api.whatsapp).toHaveLength(1);
  });

  it("falls back to email after 30 min, then emails with every reminder", async () => {
    await recordInbound(env.DB, PATIENT, ist("07:00"));
    await runMinutes(ist("08:00"), ist("08:29"));
    expect(api.emails).toHaveLength(0);
    await runMinutes(ist("08:30"), ist("08:45"));
    expect(api.emails.map((e) => e.to)).toEqual(["patient@example.com", "patient@example.com"]);
    expect(api.emails[0]!.subject).toBe("💊 Metformin 500mg: due 08:00");
    expect(api.emails[0]!.text).toContain("https://med.example.workers.dev/ack?d=");
  });

  it("emails immediately if WhatsApp fails, and retries WhatsApp every minute", async () => {
    api.failWhatsAppWith({ status: 401, code: 190, message: "token expired" });
    await runMinutes(ist("08:00"), ist("08:03"));
    expect(api.emails).toHaveLength(1);
    expect(env.DB.rows("SELECT * FROM events WHERE kind = 'whatsapp_error'")).toHaveLength(4);
    api.failWhatsAppWith(null);
    await runMinutes(ist("08:04"), ist("08:04"));
    expect(api.whatsapp).toHaveLength(1);
  });

  it("alerts the caregiver once after 90 minutes", async () => {
    await recordInbound(env.DB, PATIENT, ist("07:00"));
    await runMinutes(ist("08:00"), ist("10:00"));
    const toCaregiver = api.whatsapp.filter((m) => m.to === CAREGIVER);
    expect(toCaregiver).toHaveLength(1);
    expect(toCaregiver[0]).toMatchObject({ type: "template", template: "med_escalation", params: ["Asha", "Metformin 500mg", "08:00"] });
    expect(api.emails.filter((e) => e.to === "carer@example.com")).toHaveLength(1);
  });

  it("marks the dose missed at the cutoff and stops", async () => {
    cfg = makeConfig({ escalateAfterMin: null, meds: [{ name: "Thyroxine", times: ["06:30"], maxLateMin: 60 }] });
    await recordInbound(env.DB, PATIENT, ist("06:00"));
    await runMinutes(ist("06:30"), ist("08:00"));
    expect(dose("06:30").status).toBe("missed");
    const toPatient = api.whatsapp.filter((m) => m.to === PATIENT);
    expect(toPatient.filter((m) => m.type === "interactive")).toHaveLength(6); // 06:30 … 07:20
    expect(toPatient.at(-1)!.text).toContain("logged as *missed*");
  });

  it("still marks a snoozed dose missed at the cutoff", async () => {
    cfg = makeConfig({ meds: [{ name: "Thyroxine", times: ["06:30"], maxLateMin: 60 }] });
    await recordInbound(env.DB, PATIENT, ist("06:00"));
    await runMinutes(ist("06:30"), ist("06:30"));
    await at(ist("06:31"), () => webhook(textMessage("snooze 2h")));
    expect(api.whatsapp.at(-1)!.text).toContain("It will be logged as missed at 07:30");
    await runMinutes(ist("06:32"), ist("07:31"));
    expect(dose("06:30").status).toBe("missed");
  });
});

describe("replies", () => {
  beforeEach(async () => {
    cfg = makeConfig({
      meds: [
        { name: "Metformin 500mg", times: ["08:00"] },
        { name: "Vitamin D", times: ["08:00"] },
      ],
    });
    await recordInbound(env.DB, PATIENT, ist("07:00"));
    await runMinutes(ist("08:00"), ist("08:00"));
  });
  const byName = (name: string) => doses().find((d) => d.med_name === name)!;

  it("'taken' logs everything that's due", async () => {
    await at(ist("08:03"), () => webhook(textMessage("taken")));
    expect(byName("Metformin 500mg").status).toBe("taken");
    expect(byName("Vitamin D").status).toBe("taken");
  });

  it("'taken <name>' logs just that med and lists what's still waiting", async () => {
    await at(ist("08:03"), () => webhook(textMessage("took vitamin")));
    expect(byName("Vitamin D").status).toBe("taken");
    expect(byName("Metformin 500mg").status).toBe("pending");
    expect(api.whatsapp.at(-1)!.text).toContain("⏳ Still waiting: Metformin 500mg (08:00)");
  });

  it("replying to a specific reminder acts on that dose", async () => {
    const reminderWamid = env.DB.rows<{ wamid: string }>(
      "SELECT wamid FROM sent_messages WHERE dose_id = ?",
      byName("Metformin 500mg").id,
    )[0]!.wamid;
    await at(ist("08:03"), () => webhook(textMessage("done", { context: { id: reminderWamid } })));
    expect(byName("Metformin 500mg").status).toBe("taken");
    expect(byName("Vitamin D").status).toBe("pending");
  });

  it("template quick-reply payloads work", async () => {
    const id = byName("Vitamin D").id;
    await at(ist("08:03"), () => webhook({ id: "in.tpl", from: PATIENT, type: "button", button: { payload: `skip:${id}`, text: "Skip" } }));
    expect(byName("Vitamin D").status).toBe("skipped");
  });

  it("snooze pauses reminders and resets the email-fallback clock", async () => {
    await at(ist("08:05"), () => webhook(textMessage("snooze 30")));
    api.clear();
    await runMinutes(ist("08:06"), ist("08:34"));
    expect(api.whatsapp).toHaveLength(0);
    await runMinutes(ist("08:35"), ist("08:35"));
    expect(api.whatsapp).toHaveLength(2);
    expect(api.emails).toHaveLength(0); // only 0 min unanswered since the snooze ended
  });

  it("'taken' before anything is due logs the next dose early", async () => {
    await at(ist("08:01"), () => webhook(textMessage("taken")));
    cfg = makeConfig();
    await tick(env, cfg, ist("19:30"));
    await at(ist("19:30"), () => webhook(textMessage("taken")));
    expect(dose("20:00").status).toBe("taken");
    expect(api.whatsapp.at(-1)!.text).toBe("✅ Metformin 500mg (20:00): logged as taken (early).");
  });

  it("duplicate webhook deliveries are ignored", async () => {
    const msg = textMessage("today");
    await at(ist("08:03"), () => webhook(msg));
    await at(ist("08:03"), () => webhook(msg));
    expect(api.whatsapp.filter((m) => m.text?.startsWith("📋"))).toHaveLength(1);
  });

  it("'today' shows the day", async () => {
    await at(ist("08:03"), () => webhook(textMessage("taken metformin")));
    await at(ist("08:04"), () => webhook(textMessage("today")));
    expect(api.whatsapp.at(-1)!.text).toBe(
      "📋 Today (2026-10-19)\n✅ 08:00 Metformin 500mg: taken at 08:03\n⏳ 08:00 Vitamin D: waiting for you",
    );
  });

  it("ignores strangers; caregivers can only check status", async () => {
    await at(ist("08:03"), () => webhook(textMessage("taken", {}, "15550000000")));
    expect(byName("Vitamin D").status).toBe("pending");
    await at(ist("08:03"), () => webhook(textMessage("taken", {}, CAREGIVER)));
    expect(byName("Vitamin D").status).toBe("pending");
    expect(api.whatsapp.at(-1)).toMatchObject({ to: CAREGIVER });
    expect(api.whatsapp.at(-1)!.text).toContain("caregiver");
  });

  it("a re-engagement delivery failure switches back to the template and resends", async () => {
    const wamid = api.lastWamid();
    api.clear();
    const res = await route(
      await signedWebhook(env, webhookBody([], [{ id: wamid, status: "failed", recipient_id: PATIENT, errors: [{ code: 131047, title: "Re-engagement message" }] }])),
      env,
      cfg,
      ist("08:01"),
    );
    expect(res.status).toBe(200);
    await tick(env, cfg, ist("08:02"));
    expect(api.whatsapp.some((m) => m.type === "template")).toBe(true);
  });
});

describe("http", () => {
  it("answers Meta's webhook verification", async () => {
    const ok = await route(new Request("https://x/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=42"), env, cfg, 0);
    expect(await ok.text()).toBe("42");
    const bad = await route(new Request("https://x/webhook?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=42"), env, cfg, 0);
    expect(bad.status).toBe(403);
  });

  it("rejects unsigned or tampered webhooks", async () => {
    const req = await signedWebhook(env, webhookBody([textMessage("taken")]));
    const tampered = new Request(req.url, { method: "POST", headers: req.headers, body: JSON.stringify(webhookBody([textMessage("skip")])) });
    expect((await route(tampered, env, cfg, 0)).status).toBe(401);
    expect((await route(new Request(req.url, { method: "POST", body: "{}" }), env, cfg, 0)).status).toBe(401);
  });

  it("email links need a POST confirm, so link scanners can't ack doses", async () => {
    await tick(env, cfg, ist("08:00"));
    const id = dose("08:00").id;
    const link = await ackUrl(env, id, "taken");

    const get = await route(new Request(link), env, cfg, ist("08:05"));
    expect(get.status).toBe(200);
    expect(await get.text()).toContain("<form method=\"post\"");
    expect(dose("08:00").status).toBe("pending");

    const form = new URL(link).searchParams;
    const post = await route(
      new Request("https://med.example.workers.dev/ack", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form.toString() }),
      env,
      cfg,
      ist("08:05"),
    );
    expect(await post.text()).toContain("logged as <b>taken</b>");
    expect(dose("08:00")).toMatchObject({ status: "taken", acked_via: "email" });

    const forged = link.replace(/s=[0-9a-f]+/, "s=deadbeefdeadbeefdeadbeefdeadbeef");
    expect((await route(new Request(forged), env, cfg, ist("08:05"))).status).toBe(403);
    const otherAction = link.replace("a=taken", "a=skip");
    expect((await route(new Request(otherAction), env, cfg, ist("08:05"))).status).toBe(403);
  });
});

describe("scheduled entry point", () => {
  it("sends the daily digest once", async () => {
    cfg = makeConfig({ digestTime: "22:00" });
    await recordInbound(env.DB, PATIENT, ist("21:00"));
    await tick(env, cfg, ist("08:00"));
    await at(ist("08:02"), () => webhook(textMessage("taken")));
    api.clear();
    await runMinutes(ist("21:58"), ist("22:03"));
    const digests = api.whatsapp.filter((m) => m.text?.startsWith("📋 Summary"));
    expect(digests).toHaveLength(1);
    expect(digests[0]!.text).toContain("⏳ 20:00 Metformin 500mg: waiting for you");
    expect(digests[0]!.text).toContain("1/2 taken so far");
  });

  it("pings the healthcheck on success and /fail on a broken config", async () => {
    const e = makeEnv({ HEALTHCHECK_URL: "https://hc-ping.com/abc" });
    await runScheduled(e, cfg, ist("00:00"));
    expect(api.pings).toEqual(["https://hc-ping.com/abc"]);
    await expect(runScheduled(e, makeConfig({ timezone: "Nowhere/Land" }), ist("00:01"))).rejects.toThrow(/timezone/);
    expect(api.pings.at(-1)).toBe("https://hc-ping.com/abc/fail");
  });
});
