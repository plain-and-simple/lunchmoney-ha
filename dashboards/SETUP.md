# Lunch Money dashboard setup

Everything needed to run [`lunch-money.yaml`](lunch-money.yaml).

## 1. HACS frontend plugins

| Plugin | Repository | Why |
| --- | --- | --- |
| **auto-entities** | `thomasloven/lovelace-auto-entities` | Discovers accounts, filters by staleness, sorts, and emits the per-account cards. Nothing here works without it. |
| **Mushroom** | `piitaya/lovelace-mushroom` | `mushroom-template-card`, `mushroom-entity-card`, `mushroom-number-card`. |

No others. In particular **card-mod is not required** — the colour coding is done
through Mushroom's own `icon_color` / `badge_color`, not CSS injection.

## 2. Core setup

### `sensor.time`

Settings → Devices & Services → Add Integration → **Time & Date**, and enable the
`time` entity. The stale list references it to guarantee a re-render every
minute; without it, ages can freeze at whatever they were when the dashboard
loaded.

### The threshold helper

Settings → Devices & Services → Helpers → Create Helper → **Number**:

| Field | Value |
| --- | --- |
| Name | `Lunch Money stale hours` |
| Icon | `mdi:clock-alert-outline` |
| Min | `1` |
| Max | `336` |
| Step | `1` |
| Unit | `h` |
| Display mode | Slider |

Confirm it lands on `input_number.lunchmoney_stale_hours` — the dashboard
references that id directly. The YAML equivalent, if you prefer
`configuration.yaml`:

```yaml
input_number:
  lunchmoney_stale_hours:
    name: Lunch Money stale hours
    icon: mdi:clock-alert-outline
    min: 1
    max: 336
    step: 1
    unit_of_measurement: h
    mode: slider
```

336 hours is 14 days. Switch `mode` to `box` if dragging a slider across that
range is fiddly.

## 3. Install the dashboard

Settings → Dashboards → Add Dashboard → New dashboard from scratch → open it →
pencil → ⋮ → **Raw configuration editor** → replace the contents with
`lunch-money.yaml`.

## Notes on how it works

**Account discovery is automatic.** No entity id, account name, or budget name is
hard-coded. Accounts are found via `integration_entities('lunchmoney')` filtered
on the `source` attribute, which only the per-account balance sensors carry — the
hub totals and the diagnostic sensors do not. A bank linked next month shows up
without touching this file, matching the integration's own behaviour of adding
entities without a reload.

**Balance sensors drive both views.** All the grouping metadata (`account_type`,
`subtype`, `source`, `is_liability`) lives on the balance sensor. The stale view
hops to that account's timestamp sensor through
`device_entities(device_id(...))` rather than string-munging entity ids, so the
pairing holds even if an entity gets renamed.

**Group totals use `balance_in_primary_currency`.** That is the integration's
`to_base` field, already converted by Lunch Money — so a euro account and a
dollar account still sum to one coherent number. An account Lunch Money has no
exchange rate for contributes `0` here; the hub total sensors list those by name
in their `excluded_accounts` attribute.

**Never-updated accounts sort to the top** of the stale list rather than being
dropped. An account that has never reported a timestamp is the worst case, not
an absent one.

**Plaid connection status appears as a badge.** When a bank link is in `relink`,
`error`, `revoked`, or `not_found`, the row gets a red `mdi:link-off` badge and
the status in its subtitle. That is usually the actionable signal — it tells you
*why* the balance stopped moving, which the timestamp alone does not. Manual
accounts have no connection sensor and simply never show a badge.

## Adding a group

Copy any group section in view 2 and change the `account_type` matcher. Lunch
Money's types: `depository`, `cash`, `credit`, `investment`, `cryptocurrency`,
`employee compensation`, `loan`, `other liability`, `real estate`, `vehicle`,
`other asset`. `auto-entities` accepts a regex between slashes for matching
several at once.

If you add a type to a group, remove it from the `exclude` regex on the
**Everything else** section — otherwise it appears twice.

## Adding a label group

For groupings that do not follow account type — "Joint", "Kids", "Emergency
fund":

1. Settings → Areas, labels & zones → Labels → create the label.
2. Tag the **balance** entities with it (Settings → Entities, multi-select,
   Add label).
3. Copy the *Joint accounts* section at the bottom of view 2 and change
   `label_entities('joint')` to your label's id.

Labels beat a group helper here: an entity can carry several, membership is
managed in the UI rather than in YAML, and the same label works in automations
and service targets. Reach for a **group helper only when you want a single
rolled-up number** with hand-picked membership — for anything you would draw as
a list, the label or the attribute filter is the better tool.

## A plain table, with no plugins

**This card needs neither HACS plugin.** Everything above is built on
`auto-entities` and Mushroom. A Markdown card is core Home Assistant, so if the
freshness view is all you came for, this is the whole install. It needs no
`sensor.time` either — the timestamps it prints are absolute, so there is
nothing to re-render on the minute tick.

Every account, and the moment its balance was last known to be correct, newest
first:

```yaml
type: markdown
title: Accounts by freshness
content: |-
  | Account | Last updated |
  |---|---|
  {% for s in states.sensor
       | selectattr('entity_id', 'in', integration_entities('lunchmoney'))
       | selectattr('attributes.device_class', 'eq', 'timestamp')
       | rejectattr('state', 'in', ['unknown', 'unavailable'])
       | sort(attribute='state', reverse=true) -%}
  | {{ device_attr(s.entity_id, 'name_by_user') or device_attr(s.entity_id, 'name') }} | {{ as_local(s.state | as_datetime).strftime('%b %d, %Y %I:%M %p') }} |
  {% endfor -%}
```

Change `reverse=true` to `reverse=false` for stalest first, which is the more
useful order if you are using this to hunt for accounts you have neglected.

**It selects on `device_class`, not on the entity id.** Every other template in
this file reaches the timestamp by starting at a balance sensor and hopping
through `device_entities(device_id(e)) | select('search', '_last_updated$')`.
Here that hop is unnecessary. `last_updated` is the only per-account sensor
carrying a timestamp device class, so one filter lands on exactly one sensor per
account and steps over the balance sensors, the connection sensors and the three
budget totals at the same time. It also survives someone renaming their entity
ids, which a suffix match does not.

The account name comes off the *device* rather than the sensor. `has_entity_name`
is set, so `s.name` would give you "Chase Checking Last updated" in every row.
Asking for `name_by_user` first means a device you have renamed in Home Assistant
shows the name you chose rather than the one Lunch Money supplied.

**One thing to know:** `rejectattr` drops accounts whose timestamp is unknown, so
an account Lunch Money has never dated vanishes from a table whose whole subject
is freshness. To keep those rows, delete the `rejectattr` line and use this for
the second column instead — with the default `reverse=true` they sort to the top,
which is where they belong:

```jinja
{{ as_local(s.state | as_datetime).strftime('%b %d, %Y %I:%M %p')
   if s.state not in ['unknown', 'unavailable'] else 'Never' }}
```

## Known rough edges

- The `label:` filter key in newer `auto-entities` builds would let the label
  section use a plain `include:` block instead of a template. The template form
  in this file works on every version, so it is what shipped.
- These templates have not been run against a live instance. The `auto-entities`
  template parser is fussy about how card dicts are emitted; if a section renders
  empty, check that view's template output in Developer Tools → Template first.
