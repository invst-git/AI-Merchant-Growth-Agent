# AI Merchant Growth Agent

Built for the Razorpay AI Buildathon, Track 01.

## The problem

Most online checkouts either offer nothing extra, or offer the same generic discount or "customers also bought" list to every shopper, regardless of what is actually in their basket or what they have bought before. That approach either gets ignored, annoys the customer, or costs margin for no real reason.

The harder problem underneath this is deciding, for one specific customer and one specific basket, right now, whether an extra offer is worth making at all, and if so, exactly which one. That decision needs real data behind it, not a fixed rule and not a guess.

## The approach

This project puts two small AI agents between the customer and checkout. One agent reads what the customer wants to buy, in plain language, and matches it to a real product in the catalogue. A second agent takes that product and checks it against a decision engine trained on real historical purchase data, which scores every realistic cross-sell or upsell for that basket and either recommends the one with the best expected outcome, or recommends nothing.

The decision engine is trained on the dunnhumby "Complete Journey" dataset, over 2.5 million real transactions from 2,500 households. It learns which products people actually buy together, how likely a given household is to accept a specific offer based on its own history, and what that offer is worth once margin and the risk of a declined or ignored offer are both accounted for. An offer only goes out when a real product supports it, the household's history suggests it will land, and the expected value is positive. Otherwise the agent makes no offer, which is a common, expected outcome, not a fallback.

A separate rule checks every offer before it is shown, and blocks anything the catalogue does not actually associate with the basket, so the agent cannot recommend a product just because a model scored it well if real customers do not actually buy it alongside what is already in the cart. Every step of a transaction, from the customer's request to the final payment, is written to a log, so any single transaction can be reconstructed and explained afterward.

Payment runs on Razorpay's real Test Mode. Orders are created through Razorpay's own official server for AI agents, rather than a hand-built API call, and the customer completes a real Razorpay checkout, with the payment verified and confirmed the same way a live payment would be.

## High Level Architecture Overview
<img width="1375" height="1019" alt="image" src="https://github.com/user-attachments/assets/cda1992a-899b-42ac-a7d6-aa6b23eb7a58" />

The dunnhumby “Complete Journey” dataset is processed once, offline, into a real-time Catalogue (91,357 products) and a pair of Trained Models (a cross-sell acceptance model and an upsell propensity model, both explained per-decision with SHAP). The Decision Core combines them into one score, EV = p_accept × (Δvalue × margin) - downside, and rejects any pick the catalogue does not actually associate with the basket. Live, a customer request runs through five steps in strict order: the Buyer Agent matches a real product, the Merchant Agent asks the Decision Core for an offer, the Sales Copy LLM turns an already-decided offer into one sentence, the Gate (plain Python, not a model call) waits for accept or decline, and the Checkout Agent creates the order. Payment runs through Razorpay’s own official MCP server. Every step writes to a single append-only Audit Log, which the Dashboard reads live alongside the separate offline experiment that only ever feeds its Aggregate tab.

## How to run it

### Requirements

- Python 3.10 or newer (this project was built and tested on 3.12)
- A free Kaggle account, to download the dataset the app is trained on
- A Razorpay account with Test Mode API keys
- An Anthropic API key

### 1. Get the code and install dependencies

```
git clone https://github.com/invst-git/Agent-to-Agent-Commerce.git
cd Agent-to-Agent-Commerce
python -m venv venv
venv\Scripts\activate        # on Windows
source venv/bin/activate     # on Mac or Linux
pip install -r requirements.txt
```

### 2. Add your credentials

```
cp .env.example .env
```

Open `.env` and fill in:

- `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, from your Razorpay dashboard, Test Mode.
- `KAGGLE_USERNAME` and `KAGGLE_KEY`, from your Kaggle account settings.
- `ANTHROPIC_API_KEY`, from the Anthropic console.
- Leave `RAZORPAY_WEBHOOK_SECRET` blank for now. It is only needed for the optional webhook step further down.

Confirm the Razorpay keys work:

```
python scripts/test_razorpay_connection.py
```

This creates and fetches a real test order for one rupee. It prints a confirmation once both keys are working.

### 3. Download and prepare the data

The app is trained on one public dataset: dunnhumby's "Complete Journey" dataset on Kaggle. It is not stored in this repository, so it needs to be downloaded once.

The command below needs your Kaggle credentials in place first. Download `kaggle.json` from your Kaggle account (Account settings, then Create New API Token), and save it to the folder Kaggle expects: `~/.kaggle/kaggle.json` on Mac or Linux, or `C:\Users\<your username>\.kaggle\kaggle.json` on Windows.

```
kaggle datasets download -d frtgnn/dunnhumby-the-complete-journey -p data/raw/dunnhumby --unzip
```

Then clean and merge it into one table:

```
python data_prep/preprocess_dunnhumby.py
```

(Two other public datasets, UCI Online Retail II and the Olist Brazilian e-commerce dataset, were explored earlier in the project but are not used by the running application, so they do not need to be downloaded.)

### 4. Train the decision engine

Run these in order. Each one reads a file the previous steps produced.

```
python src/decision_engine/affinity_rules.py
python src/decision_engine/upsell_tiers.py
python src/decision_engine/household_features.py
python src/decision_engine/product_lookup.py
python src/decision_engine/household_brand_stats.py
python src/decision_engine/upsell_training_data.py
python src/decision_engine/representative_products.py
python src/decision_engine/train_acceptance_model.py --model logistic --save
python src/decision_engine/train_upsell_model.py --model gbm --save
```

This takes a few minutes. Optionally, confirm it worked:

```
python src/decision_engine/validate.py
```

This runs the trained engine against 500 real baskets and prints how often it recommends a cross-sell, an upsell, or nothing at all.

### 5. Start the application

The app runs as three small servers. Open three terminals in the project folder, and run one command in each. All three need to stay running.

```
# terminal 1: the payment service
uvicorn src.payments.checkout_api:app --port 8001 --app-dir .

# terminal 2: the dashboard
uvicorn src.dashboard.dashboard_api:app --port 8002 --app-dir .

# terminal 3: the storefront
uvicorn src.checkout_ui.app:app --port 8003 --app-dir .
```

The payment service on port 8001 handles the actual Razorpay checkout page and payment confirmation. It has to be running even though you will not open it directly.

### 6. Use it

Open `http://localhost:8003`. This is the storefront the customer talks to. Type a plain request, for example "I need a pack of beers", and send it.

The app finds a matching product, decides whether to make an offer, and if it does, shows the offer along with the reason behind it. Accept or decline the offer, then complete the payment. Use Razorpay's test UPI id `success@razorpay`, or the test card number `4111 1111 1111 1111` with any future expiry date and any three digit CVV.

Open `http://localhost:8002` in a second tab to see the same transaction appear in the dashboard, along with the full reasoning behind the decision and confirmation that it was checked against the catalogue rule before being shown.

### Optional: confirm the payment webhook

Razorpay can send a second, independent confirmation of a payment directly to the server, separate from the browser. Razorpay cannot reach a server running on your own computer directly, so this needs a public tunnel. This project uses zrok rather than ngrok, since Razorpay blocks ngrok's free tier addresses.

With the payment service (port 8001) already running, in a fourth terminal:

```
zrok share public localhost:8001
```

Copy the https address zrok prints. In the Razorpay dashboard, go to Settings, then Webhooks, then Add New Webhook. Set the URL to that address followed by `/webhooks/razorpay`, and set the event to `payment.captured`. Razorpay shows a webhook secret when you save it. Put that in `.env` as `RAZORPAY_WEBHOOK_SECRET`, then restart the payment service so it picks up the change.

### Optional: reproduce the offline experiment

The dashboard's Aggregate tab compares the agent's decisions against a plain control group across thousands of replayed past sessions. That comparison was generated once, offline, using the scripts in `src/experiment/`. It is not required to run the live demo above. The method and full results are in `docs/phase5_results.md`.

## Features

- **Understands plain language.** The customer types a normal sentence, not a product code or a form, and the app matches it to a real product in the catalogue.
- **Every offer is explained.** Each offer comes with the actual reason behind it: which products are usually bought together, how likely this household is to accept, and what the offer is worth.
- **Offers are not automatic.** The engine also considers making no offer at all, and does so for a large share of real baskets, whenever the expected outcome is not worth it.
- **Offers stay realistic.** A separate rule blocks any product the catalogue does not actually associate with the basket, so the agent cannot recommend something a model happened to score well if real customers do not buy it alongside the basket.
- **Two agents, strict roles.** One agent only reads the customer's request and looks up products. A second agent only decides on offers, using the trained model. Neither agent is allowed to invent a product, a price, or an offer that the system did not actually produce.
- **Real payments.** Every checkout is a real Razorpay Test Mode order, created through Razorpay's own official connection method for AI agents, with the payment signature verified and the payment captured the same way a live transaction would be.
- **Full audit trail.** Every step of a transaction, from the customer's request to the final payment, is logged and can be reconstructed afterward, including offers that were blocked by the catalogue rule.
- **A dashboard for visibility.** A separate view shows every transaction and the model's reasoning behind it, alongside how the agent's targeting compares to random targeting and to a group that received no offers, based on an offline test.
- **Trained on real data.** Every number the engine uses, co-purchase rates, acceptance likelihood, pricing, comes from over 2.5 million real transactions, not assumptions or made-up data.
- **Measured, not assumed, to work.** In an offline test that replayed thousands of real past baskets, the agent's offers produced a statistically significant increase in order value, and its targeting beat random targeting by close to 30 percent. Full numbers are in `docs/phase5_results.md`.

## Further reading

- `docs/objective_function.md`: the exact formula used to score every offer, and why.
- `docs/audit_schema.md`: what gets logged for each transaction.
- `docs/data_dictionary.md`: what is in the dataset, and how it was cleaned.
- `docs/phase5_results.md`: the full offline experiment, method and results.
- `docs/demo_script.md`: a scripted walkthrough for a live demo.
- `mcp/README.md`: notes on the Razorpay MCP server connection.
