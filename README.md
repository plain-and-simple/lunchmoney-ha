# Lunch Money for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/plain-and-simple/lunchmoney-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/plain-and-simple/lunchmoney-ha/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Put your [Lunch Money](https://lunchmoney.app) balances into Home Assistant, as
real entities you can chart, template against and automate on.

Paste in an access token and every account you have — bank-linked or typed in by
hand — arrives as its own device with a balance, a "last updated" timestamp, and,
for bank-linked accounts, a connection-health sensor. On top of that you get net
worth, total assets and total liabilities for the whole budget.

No `configuration.yaml`. No REST templates. No restart to pick up a new account.

## What you get

For each account, its own device:

| Entity | What it is |
| --- | --- |
| **Balance** | The current balance, as a `monetary` sensor in the account's own currency. Charts, history and long-term statistics all work. |
| **Last updated** | When Lunch Money last knew that balance to be correct. Answers "is this number stale?" — especially useful for manual accounts. |
| **Connection** | Bank-linked accounts only. `active`, `relink`, `error`, `revoked` and friends, so you can be told when a bank link dies instead of finding out weeks later. |

And for the budget as a whole:

| Entity | What it is |
| --- | --- |
| **Net worth** | Assets minus liabilities. Credit cards and loans are subtracted, not added. |
| **Total assets** | Everything you own. |
| **Total liabilities** | Everything you owe, as a positive number. |
| **Refresh from banks** | A button that asks Lunch Money to go back out to your banks now, rather than waiting for its own schedule. |

Totals use the balance Lunch Money has already converted into your primary
currency, so a household with accounts in more than one currency still gets one
coherent number.

## Install

### 1. Add the repository to HACS

In Home Assistant, go to **HACS → ⋮ → Custom repositories**, paste

```
https://github.com/plain-and-simple/lunchmoney-ha
```

choose **Integration** as the category, and click **Add**.

### 2. Install and restart

Find **Lunch Money** in HACS, click **Download**, then restart Home Assistant.

### 3. Get an access token

In Lunch Money, open **Settings → Developers** and choose **Request new access
token**. Give it a label you will recognise later — `Home Assistant` works well —
and copy the token.

### 4. Add the integration

**Settings → Devices & services → Add integration → Lunch Money**, then paste the
token.

That is the whole setup. Your accounts appear as devices within a few seconds.

### 5. Put it on a dashboard

Every balance is an ordinary sensor, so an Entities card is enough to start:

```yaml
type: entities
title: Accounts
entities:
  - sensor.family_budget_net_worth
  - sensor.chase_checking_balance
  - sensor.pennys_visa_balance
```

Your entity IDs will differ — they are built from your own account names.

## Things worth automating

**Tell me when a bank link breaks.** Lunch Money quietly stops updating a balance
when a bank needs re-authorising. The connection sensor makes that visible:

```yaml
automation:
  - alias: Lunch Money bank link needs attention
    triggers:
      - trigger: state
        entity_id: sensor.chase_checking_connection
        to:
          - relink
          - revoked
          - error
    actions:
      - action: notify.mobile_app
        data:
          message: >
            {{ trigger.to_state.attributes.friendly_name }} needs reconnecting
            in Lunch Money.
```

**Tell me when a manual balance goes stale.** Manual accounts only change when
you update them, so the timestamp is the interesting part:

```yaml
template:
  - binary_sensor:
      - name: Brokerage balance is stale
        state: >
          {{ (now() - states('sensor.fidelity_brokerage_last_updated') | as_datetime)
             .days > 30 }}
```

## Options

**Settings → Devices & services → Lunch Money → Configure**

- **Update interval** — default 15 minutes, minimum 5. Lunch Money itself only
  syncs with your banks a few times a day, so checking more often rarely shows
  you anything new.
- **Include closed accounts** — off by default, because a closed account's
  balance never changes again.
- **API version** — leave on **Automatic**. See below.

## About the API

Lunch Money has two API generations. This integration uses **v2**, which is
current, and falls back to **v1** on its own if v2 stops responding usefully —
Lunch Money describes v2 as an open alpha that may change. Your token works with
both, so nothing is needed from you either way; the fallback is logged as a
warning so a bug report can say which path was in use.

The integration only ever *reads* your data, plus asking Lunch Money to refresh
from your banks when you press the button. It never creates, edits or deletes
anything in your budget.

Your token is stored in Home Assistant and sent only to `api.lunchmoney.dev`.
Diagnostics downloads have it redacted, along with card mask digits — but read
**Reporting a bug** below before attaching one anywhere public, because your
balances are deliberately still in there.

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

The test fixtures are captured verbatim from Lunch Money's public mock server, so
the suite runs against real field names and real balance formats:

```bash
curl -H "Authorization: Bearer mocktoken123456" https://mock.lunchmoney.dev/v2/plaid_accounts
```

There is also a live check that boots a real Home Assistant against that mock
server — no real credentials involved — and proves the boot, storage and restart
paths that unit tests mock away:

```bash
./scripts/run_live_check.sh
```

## Reporting a bug

**Settings → Devices & services → Lunch Money → ⋮ → Download diagnostics** gives
you a file with most of what a bug report needs. Read it before you attach it
anywhere — a GitHub issue is public, and this file is not fully anonymous.

**Removed** — your access token, your account ID, the last four digits of each
card, and Plaid's internal identifiers.

**Kept, on purpose** — your account names, the institutions you bank with, your
balances and your credit limits.

That last part is a deliberate trade, not an oversight. Nearly every bug worth
reporting here is some version of "the number is wrong", and that is not
diagnosable without the numbers. Redacting them would mostly mean asking you for
them again.

So: it tells anyone reading where you bank and how much is in each account. If
that's fine, attach it as-is — it is by far the most useful thing you can send.
If it isn't, open it in a text editor and replace the balances first, or email
it instead of posting it. Either is more useful than no diagnostics at all.

## Not included (yet)

Budget and category sensors, and spending totals derived from transactions.
Both are planned; balances came first because they are what most people want on
a dashboard.

## Licence

MIT. Not affiliated with or endorsed by Lunch Money.
