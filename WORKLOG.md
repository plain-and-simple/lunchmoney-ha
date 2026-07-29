# Worklog

## 2026-07-28 — A core-only freshness table

Added a plain Markdown card to `dashboards/SETUP.md` — account name and the
moment its balance was last known to be correct, ordered by that timestamp — plus
a pointer from the README to `dashboards/`, which nothing linked to before. No
integration code was touched.

### Decisions and why

**It selects on `device_class: timestamp` rather than the `_last_updated$`
suffix.** `last_updated` is the only per-account sensor carrying that device
class, so one filter lands on exactly one sensor per account and steps over the
balance sensors, the connection sensors and the three budget totals at the same
time. No `device_entities(device_id(...))` hop, and it survives a user renaming
their entity ids — which the suffix match does not.

**First card here that needs no HACS frontend plugin.** Everything in
`lunch-money.yaml` that renders account data is `auto-entities` or Mushroom.
Freshness is the view people want first, and two plugin installs is a steep floor
to put in front of it.

**The timestamp sensor's state is read directly, rather than `last_changed`.**
The state *is* `balance_as_of`, so it answers "when was this balance correct"
instead of "when did Home Assistant last see this number move" — very different
answers for an account whose balance happens to be flat.

### Open items

- The `balance_as_of`-as-attribute idea below is weaker than it was. This card
  reaches the timestamp with no `device_id` hop and no per-state-change attribute
  cost, so the hop is now only a cost in the `auto-entities` views.
- Untested against a live instance, like the rest of `dashboards/`.

## 2026-07-26 — Dashboards

Added `dashboards/lunch-money.yaml` and `dashboards/SETUP.md`. No integration
code was touched.

### Two views

- **Stale data** — every account whose `last_updated` is older than an
  adjustable threshold, most stale first, colour-coded, with a red badge on
  Plaid accounts whose bank link is broken.
- **Groups** — accounts sectioned by `account_type` (credit cards, banking,
  investments, loans, property), with a per-group total, plus a label-driven
  section for groupings that do not follow type.

### Decisions and why

**Built on `auto-entities` + Mushroom, not a custom card.** A HACS repository
declares a single category, so shipping a Lovelace card would need a second
repo, its own JS build, and a separate install step per user. The two plugins
already cover it.

**Grouping reads the `account_type` attribute rather than a group helper.**
Group helpers give one combined *state* with hand-maintained membership — wrong
shape for a list, and stale the moment a card is added. The attribute filter
self-maintains.

**HA Labels for non-type groupings**, over group helpers: UI-managed, an entity
can hold several, and the same label works in automations.

**Both views are driven off the balance sensors**, hopping to the timestamp
sensor via `device_entities(device_id(...))`. All the grouping metadata lives on
the balance sensor (`sensor.py:103-112`); `last_updated` carries none. Entities
are selected on the `source` attribute — unique to per-account balance sensors —
so no entity id or budget name is hard-coded anywhere.

**Never-updated accounts sort as most stale** rather than being filtered out.

### Open items

- Templates are untested against a live instance. `auto-entities`' template
  parser is the likely source of any breakage.
- If the templates prove awkward, the cheap fix is on the integration side:
  adding `balance_as_of` to the balance sensor's attributes would remove the
  `device_entities` / `device_id` hop from the stale view entirely. Deliberately
  not done yet — it is a real attribute-storage cost per state change, and worth
  paying only if the current approach actually hurts.
