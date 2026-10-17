# 💊 Med Reminder

**Never wonder "did I take my pills?" again.**

Med Reminder messages you on WhatsApp when it's time for your medicine, and **keeps reminding you every 10 minutes until you reply**. There's no app to install, nothing to open and no dashboard. Just a message you can't ignore, and one tap to say you took it.

<p align="center"><i>What you'll see on your phone:</i></p>

```
💊 Metformin 500mg
with food
Due 08:00 · 20 min late · reminder #3

  [ ✅ Taken ]   [ 💤 Snooze 30 min ]   [ ⏭ Skip ]
```

Tap **✅ Taken** and it goes quiet until the next dose.

---

## What it does for you

- **Reminds you on time.** A WhatsApp message arrives at each dose time you set.
- **Doesn't let you forget.** No reply? You get another reminder every 10 minutes, each one showing how late you are.
- **Reaches you another way.** Still no reply after 30 minutes? Reminders start arriving by email too, with one-tap buttons.
- **Can tell someone who cares.** Optionally, after 90 minutes, a family member or caregiver gets one heads-up message.
- **Knows when to stop.** Some medicines shouldn't be taken hours late. After a limit you choose, it stops reminding, logs the dose as missed and tells you.
- **Wraps up your day.** At night you get a short summary of what you took, skipped or missed.
- **Tells you if it ever breaks.** An optional free watchdog alerts you if the reminder service itself stops running, so silence never means "all good" by mistake.

## A day with Med Reminder

| Time | What happens |
|---|---|
| 08:00 | 💊 *"Metformin 500mg, with food. Due now."* You're making breakfast and don't see it. |
| 08:10 | 💊 Reminder #2: *"10 min late."* |
| 08:12 | You tap **✅ Taken**. *"✅ Metformin 500mg (08:00): logged as taken."* Quiet again. |
| 20:00 | 💊 Evening dose. You're driving, so you tap **💤 Snooze 30 min**. |
| 20:30 | 💊 Reminder again. You reply `done`. ✅ |
| 22:00 | 📋 *"Summary for today: 2/2 taken."* |

## Talking to it

Tap the buttons, or just type. It understands plain words:

| Send this | What happens |
|---|---|
| `taken` (or `done`, `took`, `yes`, ✅) | Logs what's due right now as taken |
| `taken metformin` | Logs just that medicine |
| `skip` | Skips this dose and stops reminders for it |
| `snooze` / `snooze 15` / `snooze 1h` | "Ask me again later" (30 min if you don't say) |
| `today` | Shows today's doses and what's done |
| anything else | Shows this list |

**Took it early?** Reply `taken` up to an hour before a dose and it's logged, so that reminder never comes.

**Two medicines at once?** `taken` logs both. To log only one, reply directly to its reminder (swipe right on the message in WhatsApp) or name it.

## Your schedule

Your medicines live in one small file, `meds.config.ts`. It reads like a list:

```ts
meds: [
  { name: "Metformin 500mg", times: ["08:00", "20:00"], note: "with food" },
  { name: "Vitamin D",       times: ["09:00"], days: ["mon", "thu"] },
  { name: "Thyroxine",       times: ["06:30"], note: "empty stomach", maxLateMin: 120 },
],
```

- **times**: 24-hour clock, e.g. `"07:30"`, `"21:00"`
- **days** *(optional)*: only on these days. Leave it out for every day.
- **note** *(optional)*: shown on every reminder, e.g. "with food"
- **maxLateMin** *(optional)*: stop reminding and log as missed after this many minutes (default: 4 hours)

Change the file, run `npm run deploy`, done. If you make a typo (like `"8:00"` instead of `"08:00"`), it refuses to update and tells you what's wrong, so a mistake can never silently skip a dose.

You can also change, at the top of the same file: the reminder interval (10 min), when email kicks in (30 min), when your caregiver hears (90 min), your time zone and the summary time.

---

## Getting started

Setup takes about **45 minutes, once**. After that you never touch it again unless your prescription changes.

**You'll need:**
- A computer with [Node.js](https://nodejs.org) (version 20 or newer)
- A free [Cloudflare account](https://dash.cloudflare.com/sign-up). This is where the reminder service lives.
- A free [Meta developer account](https://developers.facebook.com/). This is what lets it send WhatsApp messages.
- *(optional)* A free [Resend](https://resend.com) account for email reminders
- *(optional)* A free [healthchecks.io](https://healthchecks.io) account for the "is it still running?" alarm

### Step 1: Get the service running on Cloudflare

```bash
git clone https://github.com/invst-git/med-reminder.git
cd med-reminder
npm install
npx wrangler login                    # opens your browser to sign in to Cloudflare
npx wrangler d1 create med-reminder   # creates your private database
```

The last command prints a `database_id`. Open `wrangler.toml` and paste it where it says `REPLACE_WITH_YOUR_D1_DATABASE_ID`. Then:

```bash
npm run db:migrate
npx wrangler deploy
```

This prints your service's web address, something like `https://med-reminder.yourname.workers.dev`. Copy it into `PUBLIC_URL` in `wrangler.toml`.

### Step 2: Create your WhatsApp sender

Meta (WhatsApp's owner) gives you a free test number to send from. It shows up in your WhatsApp as the chat that reminds you.

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) and click **Create app**. Pick **Connect with customers through WhatsApp** (or app type **Business**), and follow the prompts.
2. In your new app, open **WhatsApp → API Setup**.
   - Note the **Phone number ID**. You'll need it soon.
   - Under **To**, add **your own WhatsApp number** and enter the code WhatsApp sends you. Add your caregiver's number here too if you want them alerted (up to 5 numbers).
3. Get a **permanent key**. The one on that page expires after a day.
   1. Go to [business.facebook.com](https://business.facebook.com) → **Settings → Users → System users → Add**, and make it an **Admin**.
   2. Click **Assign assets**, then give it your app (full control) and your WhatsApp account.
   3. Click **Generate token**. Choose your app, set expiry to **Never**, and tick `whatsapp_business_messaging` and `whatsapp_business_management`. Copy the token somewhere safe.
4. In your app's **App settings → Basic**, reveal and copy the **App secret**.

### Step 3: Set up the "are you there?" message

WhatsApp lets the service message you freely for 24 hours after **you** last messaged it. Since you tap ✅ a few times a day, that's almost always the case. For the rare day you go quiet, WhatsApp requires a pre-approved message, so you create one once.

In **WhatsApp Manager → Message templates → Create template**:

| Field | Enter |
|---|---|
| Category | **Utility** |
| Name | `med_reminder` |
| Language | **English** |
| Message | `💊 Time for your medication: {{1}} (due {{2}}). Tap Taken once you've had it.` |
| Sample values | `{{1}}` → `Metformin 500mg`, `{{2}}` → `08:00` |
| Buttons | Add **Quick reply** → `Taken`, then another **Quick reply** → `Snooze 30 min` |

<details>
<summary><b>Optional:</b> a template for caregiver alerts on WhatsApp (not needed for caregiver email)</summary>

| Field | Enter |
|---|---|
| Category | Utility |
| Name | `med_escalation` |
| Message | `🔔 {{1}} hasn't confirmed taking {{2}}, due at {{3}}.` |

Then in `wrangler.toml` set `WHATSAPP_ESCALATION_TEMPLATE = "med_escalation"`.
</details>

Approval usually takes a few minutes. If you chose "English (US)" instead of "English", set `WHATSAPP_TEMPLATE_LANG = "en_US"` in `wrangler.toml`.

### Step 4: Give the service your details

Each command below asks you to paste a value. They're stored encrypted on Cloudflare, never in the code. Phone numbers are digits only with the country code, e.g. `919876543210` for India or `14155551234` for the US.

```bash
npx wrangler secret put WHATSAPP_TOKEN            # the permanent key from step 2
npx wrangler secret put WHATSAPP_PHONE_NUMBER_ID  # the Phone number ID from step 2
npx wrangler secret put WHATSAPP_APP_SECRET       # the App secret from step 2
npx wrangler secret put WHATSAPP_VERIFY_TOKEN     # make up any password-like text, and remember it
npx wrangler secret put ACK_SECRET                # make up another one (you won't need it again)
npx wrangler secret put PATIENT_WHATSAPP          # your WhatsApp number
```

Optional extras:

```bash
npx wrangler secret put PATIENT_EMAIL             # your email, for email reminders
npx wrangler secret put RESEND_API_KEY            # from resend.com, enables email
npx wrangler secret put CAREGIVER_WHATSAPP        # your caregiver's number
npx wrangler secret put CAREGIVER_EMAIL           # your caregiver's email
npx wrangler secret put HEALTHCHECK_URL           # from healthchecks.io (see step 7)
```

In `wrangler.toml`, set `PATIENT_NAME` to how your caregiver knows you (e.g. `"Mom"`). Then put your medicines in `meds.config.ts` and run:

```bash
npm run deploy
```

### Step 5: Connect WhatsApp to the service

Back in your Meta app, open **WhatsApp → Configuration → Webhook → Edit**:

- **Callback URL**: your web address from step 1, plus `/webhook`, e.g. `https://med-reminder.yourname.workers.dev/webhook`
- **Verify token**: the password-like text you made up for `WHATSAPP_VERIFY_TOKEN`

Click **Verify and save**. Then under **Webhook fields**, turn on **messages**.

### Step 6: Say hi 👋

Open WhatsApp and send **hi** to the test number. It replies with the list of things you can say. **You're all set**, and your first reminder arrives at your next dose time.

### Step 7 (recommended): The "is it still running?" alarm

The worst thing a reminder can do is go silent without you noticing. [healthchecks.io](https://healthchecks.io) is free and watches for that:

1. Create a check with **Period: 1 minute** and **Grace: 5 minutes**.
2. Choose how it should alert you (email, or one of its messaging integrations).
3. Copy its ping URL and run `npx wrangler secret put HEALTHCHECK_URL`.

If the service ever stops, you'll hear about it within minutes.

<details>
<summary><b>Email reminders: a note about Resend</b></summary>

Resend's free plan sends up to 3,000 emails a month, plenty for this. Out of the box it can only email **the address you signed up to Resend with**. That's perfect for reminding yourself. To email a caregiver at a different address, [add a domain you own](https://resend.com/domains) and change `EMAIL_FROM` in `wrangler.toml`.
</details>

---

## Questions

**Does it cost anything?**
Practically nothing. Cloudflare's free plan covers it. WhatsApp messages are free while you've replied within the last 24 hours, which is normal daily use. If you go a full day without replying, the next reminder is a "utility" message that costs a fraction of a cent in most countries ([Meta's pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)).

**What if I don't see WhatsApp for a while?**
It keeps trying every 10 minutes, starts emailing after 30, and (if you set one up) alerts your caregiver after 90. Each step is adjustable.

**What happens to a dose I really missed?**
After the limit you set for that medicine, it stops reminding and logs the dose as *missed*, so it never nudges you into a dangerously late dose. Check with your doctor or pharmacist about what to do when you miss one.

**Can I see my history?**
Send `today` for today. Every reminder and reply is also kept in your private database (see *For the technically curious* below), which is handy to show a doctor.

**I'm travelling to another time zone.**
Change `timezone` at the top of `meds.config.ts` (e.g. `"Europe/London"`) and run `npm run deploy`. Daylight-saving changes are handled automatically.

**Who can see my information?**
Only you. It runs on your own Cloudflare account. Your phone numbers and emails are stored as encrypted secrets. Messages from numbers other than yours (and your caregiver's) are ignored. Your caregiver can only ask for `today`; they can't mark doses for you. If you keep this code in a **public** GitHub repository, your medicine names in `meds.config.ts` would be visible, so keep the repository private.

**Could my email app mark a dose as taken by itself?**
No. Some email apps open links automatically to scan them, so the email buttons open a page that asks you to confirm with one more tap. Each button is also signed and works only for its own dose. Anyone you forward the email to could use it, though, so don't forward reminder emails.

---

## For the technically curious

<details>
<summary>Logs, history and how it works</summary>

**Check on it:**

```bash
npx wrangler tail     # live log
npx wrangler d1 execute med-reminder --remote \
  --command "SELECT local_date, local_time, med_name, status FROM doses ORDER BY due_at DESC LIMIT 20"
npx wrangler d1 execute med-reminder --remote \
  --command "SELECT datetime(at/1000,'unixepoch'), kind, detail FROM events ORDER BY id DESC LIMIT 30"
```

**How it works:** a Cloudflare Worker wakes up every minute. It creates the day's doses from your schedule, sends anything due, repeats unanswered reminders every 10 minutes, and handles the email, caregiver and missed steps. Your WhatsApp replies arrive at the Worker's `/webhook` address, which checks Meta's signature, ignores duplicates and updates the dose. Everything is stored in a Cloudflare D1 (SQLite) database.

**Built to be dependable:**
- Two overlapping runs can never send the same reminder twice.
- If WhatsApp says the 24-hour window has closed, it switches to the approved template and resends.
- If WhatsApp fails entirely (expired key, outage), it emails you right away and keeps retrying WhatsApp every minute.
- Doses for tomorrow are prepared a day ahead.
- Adding a medicine mid-day won't fire reminders for times already well past.

**Development:**

```bash
npm test          # 36 automated tests, incl. time zones and full remind → reply flows
npm run check     # type check + tests (also runs before every deploy)
npm run dev       # run locally; trigger a tick with: curl "localhost:8787/__scheduled?cron=*+*+*+*+*"
```

| File | What's in it |
|---|---|
| `meds.config.ts` | **Your schedule and preferences** |
| `src/scheduler.ts` | The every-minute loop: reminders, repeats, email, caregiver, missed, summary |
| `src/inbound.ts`, `src/commands.ts` | Understanding your replies |
| `src/whatsapp.ts`, `src/email.ts`, `src/notify.ts` | Sending messages |
| `src/time.ts` | Time zones and daylight saving |
| `migrations/0001_init.sql` | Database layout |
</details>

---

<sub>Med Reminder helps you remember and keeps a record. It is not medical advice. Always follow your doctor's or pharmacist's instructions.</sub>
