# med-reminder

A medication reminder with no app and no dashboard. At each dose time it messages you on **WhatsApp** and **repeats every 10 minutes until you reply**. If you still haven't answered after 30 minutes it starts emailing you too, and after 90 minutes it can alert a caregiver. It runs on a Cloudflare Worker (free plan) with a D1 database.

```
💊 Metformin 500mg
with food
Due 08:00 · 20 min late · reminder #3
[ ✅ Taken ]  [ 💤 Snooze 30 min ]  [ ⏭ Skip ]
```

## How it behaves

| When | What happens |
|---|---|
| Dose time | WhatsApp reminder with buttons |
| Every 10 min, still no reply | The reminder repeats ("reminder #4, 30 min late") |
| 30 min with no reply | Each reminder also goes by email, with one-click Taken / Snooze / Skip links |
| 90 min with no reply | The caregiver gets one alert (WhatsApp and/or email) |
| `maxLateMin` passed (default 4 h) | The dose is logged as **missed** and reminders stop, so a very late dose isn't encouraged |
| 22:00 | Summary of the day |
| Worker stops running | healthchecks.io alerts you (optional, recommended) |

## Replying

Tap a button, or reply with text:

| You send | Effect |
|---|---|
| `taken` (also `done`, `took`, `yes`, ✅) | Logs everything currently due as taken. If nothing is due, logs the next dose in the coming hour as taken early. |
| `taken metformin` | Logs only that med |
| `skip` / `skip vitamin d` | Skips the dose (reminders stop) |
| `snooze` / `snooze 15` / `snooze 1h` | Pauses reminders for that long (default 30 min) |
| `today` | Today's doses and their status |
| anything else | Help |

If you **reply to a specific reminder** (swipe right on it in WhatsApp), the command applies to that dose only.

## Your schedule

Edit [`meds.config.ts`](meds.config.ts), then run `npm run deploy`:

```ts
meds: [
  { name: "Metformin 500mg", times: ["08:00", "20:00"], note: "with food" },
  { name: "Vitamin D", times: ["09:00"], days: ["mon", "thu"] },
  { name: "Thyroxine", times: ["06:30"], note: "empty stomach", maxLateMin: 120 },
],
```

Times are 24-hour `HH:MM` in the configured `timezone`. `npm run deploy` runs a validator first, so a typo like `"8:00"` stops the deploy instead of silently missing a dose. Doses whose time had already passed by more than 15 minutes when they were first created (at your first deploy, or when you add a med mid-day) are skipped rather than nagged.

> **Privacy:** if this folder is in a public GitHub repo, your med names are public too. Phone numbers and emails are kept in Cloudflare secrets, never in the code.

---

## Setup (about 45 minutes, one time)

You need Node 20+, a free [Cloudflare account](https://dash.cloudflare.com/sign-up) and a free [Meta developer account](https://developers.facebook.com/).

### 1. Cloudflare: create the database and deploy once

```bash
cd med-reminder
npm install
npx wrangler login
npx wrangler d1 create med-reminder      # copy the database_id it prints
```

Paste the `database_id` into `wrangler.toml`, then:

```bash
npm run db:migrate                       # creates the tables
npx wrangler deploy                      # prints your URL, e.g. https://med-reminder.yourname.workers.dev
```

Put that URL in `PUBLIC_URL` in `wrangler.toml`. You'll deploy again at the end.

### 2. Meta: create the WhatsApp sender

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps), click **Create app**, choose the use case **Connect with customers through WhatsApp** (or type **Business**), and finish creating it. Create a business portfolio if asked.
2. Open **WhatsApp → API Setup**. Meta gives you a free **test number**.
   - Copy the **Phone number ID**. This is `WHATSAPP_PHONE_NUMBER_ID`, not the phone number itself.
   - Under **To**, add **your own WhatsApp number** and verify it with the code Meta sends you. A test number can message up to 5 verified numbers: you, plus a caregiver if you want one.
3. Create a **permanent access token**. The token on the API Setup page expires in 24 hours.
   - Go to [business.facebook.com](https://business.facebook.com) → **Settings → Users → System users → Add**. Make it an Admin.
   - **Assign assets**: pick your app with full control, and your WhatsApp account.
   - **Generate token**: choose your app, set expiry to **Never**, and tick `whatsapp_business_messaging` and `whatsapp_business_management`. This is `WHATSAPP_TOKEN`.
4. **App secret**: App dashboard → **App settings → Basic → App secret → Show**. This is `WHATSAPP_APP_SECRET`.

> Later, if you want, you can add your own number (a spare SIM that isn't registered in the WhatsApp app) under **WhatsApp → API Setup → Add phone number**. The test number is fine for personal use.

### 3. Meta: create the message template

WhatsApp only lets a business send free-form messages within **24 hours of your last message to it**. Since you tap ✅ several times a day, that window is almost always open and the reminders are free. When it's closed (say you didn't reply for a whole day), the bot sends an approved **template** instead. That is the only kind of message that might cost money (fractions of a cent).

Go to **WhatsApp Manager → Message templates → Create template**:

| Field | Value |
|---|---|
| Category | **Utility** |
| Name | `med_reminder` |
| Language | English (`en`). If you pick "English (US)", set `WHATSAPP_TEMPLATE_LANG = "en_US"` in `wrangler.toml` |
| Body | `💊 Time for your medication: {{1}} (due {{2}}). Tap Taken once you've had it.` |
| Body samples | `{{1}}` = `Metformin 500mg`, `{{2}}` = `08:00` |
| Buttons | Quick reply → **Taken**, then Quick reply → **Snooze 30 min** (in this order) |

**Optional caregiver alert template**, needed only for WhatsApp alerts to a caregiver (email alerts work without it):

| Field | Value |
|---|---|
| Category | Utility |
| Name | `med_escalation` |
| Body | `🔔 {{1}} hasn't confirmed taking {{2}}, due at {{3}}.` |

Then set `WHATSAPP_ESCALATION_TEMPLATE = "med_escalation"` in `wrangler.toml`.

Approval usually takes minutes.

### 4. Set the secrets

Digits only for phone numbers, with country code (India: `91…`, US: `1…`).

```bash
npx wrangler secret put WHATSAPP_TOKEN
npx wrangler secret put WHATSAPP_PHONE_NUMBER_ID
npx wrangler secret put WHATSAPP_APP_SECRET
npx wrangler secret put WHATSAPP_VERIFY_TOKEN     # make up any random string, e.g. from: openssl rand -hex 16
npx wrangler secret put ACK_SECRET                # another random string
npx wrangler secret put PATIENT_WHATSAPP          # e.g. 919876543210

# optional
npx wrangler secret put PATIENT_EMAIL
npx wrangler secret put CAREGIVER_WHATSAPP
npx wrangler secret put CAREGIVER_EMAIL
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put HEALTHCHECK_URL
```

Set `PATIENT_NAME` in `wrangler.toml` (used in caregiver alerts), then deploy:

```bash
npm run deploy
```

### 5. Meta: connect the webhook

In the app dashboard, open **WhatsApp → Configuration → Webhook → Edit**:

- **Callback URL**: `https://med-reminder.yourname.workers.dev/webhook`
- **Verify token**: the same string you used for `WHATSAPP_VERIFY_TOKEN`

Click **Verify and save**, then under **Webhook fields** subscribe to **messages**.

### 6. Say hi

Send **hi** to the test number from your WhatsApp. You should get the help message back. This also opens the 24-hour window, so the next reminder arrives with buttons.

### 7. Email fallback (optional)

Sign up at [resend.com](https://resend.com) (free tier: 3,000 emails/month), create an API key and set `RESEND_API_KEY`. The default sender `onboarding@resend.dev` only delivers to the email address you signed up to Resend with. That's fine for emailing yourself. To email a caregiver at a different address, [verify a domain](https://resend.com/domains) and change `EMAIL_FROM`.

Email links open a page with a confirm button rather than acting immediately. Mail scanners open links automatically, and they shouldn't be able to mark a dose as taken.

### 8. Dead-man's switch (recommended)

If the Worker ever stops running, the worst outcome is silence. Create a free check at [healthchecks.io](https://healthchecks.io) with **period 1 minute, grace 5 minutes**, connect an alert channel (email, or their Telegram/WhatsApp integrations), and set its ping URL as `HEALTHCHECK_URL`. Every run pings it, and a broken config pings `/fail`.

---

## Operating it

```bash
npx wrangler tail                         # live logs
npx wrangler d1 execute med-reminder --remote \
  --command "SELECT local_date, local_time, med_name, status, send_count FROM doses ORDER BY due_at DESC LIMIT 20"
npx wrangler d1 execute med-reminder --remote \
  --command "SELECT datetime(at/1000,'unixepoch'), kind, detail FROM events ORDER BY id DESC LIMIT 30"
```

`events` is the full audit log: every reminder, error and acknowledgement.

**Costs:** Cloudflare Workers, D1 and Cron Triggers fit comfortably in the free plan. WhatsApp messages inside the 24-hour window are free. A template sent while the window is closed is a "utility" message, which Meta prices at fractions of a cent in most countries (see [Meta's pricing page](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)).

## Development

```bash
npm test          # 36 tests: time zones and DST, parsing, and full reminder → reply flows against real SQLite
npm run check     # typecheck + tests
npm run dev       # local Worker; trigger the cron with: curl "localhost:8787/__scheduled?cron=*+*+*+*+*"
```

| File | Role |
|---|---|
| `src/index.ts` | Entry: `/webhook` (Meta), `/ack` (email links), the every-minute cron |
| `src/scheduler.ts` | Creates doses, sends reminders and repeats, email fallback, caregiver alert, missed doses, daily digest |
| `src/inbound.ts` | Handles your replies, button taps and delivery failures |
| `src/commands.ts` | Parses `taken`, `snooze 15`, etc. |
| `src/notify.ts`, `src/whatsapp.ts`, `src/email.ts` | Delivery: buttons vs. template (24h window), Resend, signed ack links |
| `src/time.ts` | Time-zone and DST-safe local ↔ UTC conversion |
| `migrations/0001_init.sql` | D1 schema |
| `meds.config.ts` | **Your schedule** |

Reliability details: sends are claimed with a conditional update, so overlapping cron runs can't double-send. Webhooks are signature-checked and de-duplicated. Repeat timing allows for cron jitter, so "every 10 minutes" doesn't drift to 11. If WhatsApp reports that the 24-hour window has closed, the bot switches back to the template and resends. If the WhatsApp send fails outright (expired token, Meta outage), it emails you immediately and retries WhatsApp every minute.

*This tool reminds and records. It doesn't give medical advice. Ask your doctor or pharmacist what to do about a missed dose.*
