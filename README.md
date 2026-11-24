# Airwallex Payment Provider for Odoo 19

An Odoo payment-provider addon that integrates Airwallex Drop-in Checkout with Odoo's payment framework.

- **Odoo addon technical name:** `payment_airwallex`
- **Odoo compatibility:** 19.0
- **License:** LGPL-3.0 (see the addon manifest)

## Features

- Airwallex Drop-in Checkout embedded in the Odoo payment form.
- PaymentIntent creation and reuse.
- Payment status updates from Airwallex webhooks.
- Webhook HMAC signature and timestamp verification.
- Odoo payment-status return route.
- Currency-specific payment method allow-lists.

## Payment method availability

The frontend explicitly configures the Drop-in methods by transaction currency:

| Transaction currency | Methods passed to Airwallex Drop-in |
| --- | --- |
| CNY | WeChat Pay |
| SGD | PayNow |
| Other currencies | Card, Apple Pay, Google Pay |

WeChat Pay is only included for CNY. PayNow is only included for SGD. Other currencies do not receive either method in the Drop-in configuration.

Airwallex may further filter methods based on the merchant account, shopper country, currency, device, and method eligibility. The methods shown at checkout are therefore subject to Airwallex account and regional availability.

**HKD availability is not hard-coded in this addon.** Configure the Airwallex provider's available currencies in Odoo to exclude HKD where required.

## Requirements

The addon manifest declares these Odoo dependencies:

- `payment`
- `website_payment`
- `website`

The Airwallex merchant account must have the relevant payment methods enabled. WeChat Pay H5 also has separate Airwallex onboarding, domain-review, and scheme requirements; enabling the method in the frontend does not replace those requirements.

## Installation

### Manual installation

1. Copy this addon directory into an Odoo custom addons path.
2. The directory name must be `payment_airwallex`, so Odoo can load it as the `payment_airwallex` technical module.
3. Ensure the custom addons path is included in the Odoo `addons_path`.
4. Restart the Odoo service.
5. In Odoo, update the Apps List and install **Payment Provider: Airwallex**.

Example target path:

```text
/opt/odoo/addons/payment_airwallex
```

### Git installation

The Git repository name may differ from the Odoo addon technical name. Clone the repository into a directory named `payment_airwallex`.

Current repository URL:

```bash
git clone https://github.com/a123aos/airwallex-dropin-odoo-payment.git payment_airwallex
```

After cloning, add the parent directory to Odoo's `addons_path`, restart Odoo, update the Apps List, and install the module.

To update a Git-managed installation:

```bash
cd /opt/odoo/addons/payment_airwallex
git pull --ff-only origin main
```

If the repository is renamed on GitHub, update the Git remote URL in the cloned directory:

```bash
git remote set-url origin https://github.com/a123aos/payment_airwallex.git
git remote -v
```

Do not run Git commands inside a manually copied addon directory unless it has first been cloned as a Git repository.

## Configuration

1. Open **Website / Accounting → Configuration → Payment Providers** (the exact menu can vary with installed Odoo apps).
2. Open the Airwallex provider.
3. For Sandbox testing, set the provider to **Test** and enter the Sandbox Client ID and API Key.
4. For live payments, set the provider to **Enabled** and enter the corresponding live credentials.
5. Publish the provider when it is ready to appear at checkout.
6. Configure the provider's available currencies in Odoo. This addon does not hard-code HKD availability.

The addon selects the Airwallex API environment from the Odoo provider state:

- Provider state `test` (and other non-`enabled` states): Airwallex Demo API and Drop-in environment.
- Provider state `enabled`: Airwallex Production API and Drop-in environment.

**Do not mix Sandbox credentials with an Enabled/Production provider.** Keep Client IDs, API Keys, and Webhook Secrets private.

## Webhooks and return URL

Configure an Airwallex webhook that points to:

```text
https://<your-public-odoo-domain>/payment/airwallex/webhook
```

Store the matching webhook signing secret in the Airwallex provider's **Webhook Secret** field in Odoo.

The addon verifies the webhook signature using the timestamp and raw request body, and rejects timestamps outside its configured tolerance.

The PaymentIntent return route is:

```text
https://<your-public-odoo-domain>/payment/airwallex/return
```

The base URL configured in Odoo must be the publicly reachable HTTPS URL used by the checkout. A local-only address such as `localhost` is not accessible to a customer's phone or to Airwallex.

The return route sends the browser to Odoo's `/payment/status` page. The return route does not itself mark a transaction as paid; the payment state is updated through the webhook processing flow.

## Implementation overview

- `models/payment_provider.py`: provider credentials, API authentication, PaymentIntent creation, and provider feature configuration.
- `models/payment_transaction.py`: transaction processing values, webhook state mapping, and event de-duplication.
- `controllers/main.py`: Airwallex webhook endpoint, signature validation, and browser return endpoint.
- `static/src/interactions/payment_form.js`: Airwallex SDK initialization and Drop-in setup.
- `views/payment_airwallex_templates.xml`: inline payment container and currency-specific payment-method logos.
- `views/payment_provider_views.xml`: provider credential fields.

## Testing checklist

Before enabling live payments, test at least:

- CNY checkout: WeChat Pay is the only configured local method.
- SGD checkout: PayNow is the only configured local method.
- A non-CNY/non-SGD currency: WeChat Pay and PayNow are absent; Card, Apple Pay, and Google Pay are configured.
- A successful Sandbox payment updates the Odoo transaction through the webhook.
- The browser return route restores the Odoo payment-status flow.
- Webhook retries do not cause duplicate state processing.

Availability of Apple Pay, Google Pay, cards, WeChat Pay, and PayNow depends on the Airwallex merchant account and shopper/device eligibility.

## Scope and cautions

- This README describes the current online checkout integration. It does not certify every payment method for every country, currency, device, or Airwallex account.
- Refund, tokenization, and manual-capture workflows require separate end-to-end validation before being enabled in a live business process.
- No automated test suite is currently included in this repository.
- Always test changes with Airwallex Sandbox before deploying them to a production Odoo database.

## License

This addon declares **LGPL-3.0** in `__manifest__.py`.
