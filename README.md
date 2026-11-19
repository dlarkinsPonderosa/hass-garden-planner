<img src="custom_components/reap/brand/icon.png" alt="Reap icon" width="96" align="right">

# Reap for Home Assistant

*Reap what you Sow.*

Turns a list of crops into dated garden tasks on a Home Assistant to-do list:
sowing indoors, potting up, hardening off, transplanting, direct sowing,
covering and harvest. It handles three ways of growing (indoor starts under
lights, beds, heated greenhouse), repeat sowings such as carrots every week,
and moves later tasks when you tick one off early or late.

It works anywhere in a temperate climate: every crop's timing is stored as
days before or after the last spring frost and the first fall frost, so your
own frost dates turn it into a calendar for your garden. A climate profile
handles how fast spring warms up after the last frost, which hardiness zones
don't capture.

The built-in crop catalog is transcribed from West Coast Seeds' *South Coastal
BC Vegetable Planting Guide* (49 crops) and the herbs from its *Flower & Herb
Planting Guide* (22 herbs), plus potato and tomatillo. You can add your own
crops and varieties.

## Install

1. In HACS, open the three-dot menu, choose **Custom repositories**, add
   `https://github.com/dlarkinsPonderosa/hass-garden-planner` as an
   **Integration**, then download **Reap**.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration > Reap**.

### Upgrading from Garden Planner (0.2.x)

Version 0.3.0 renamed the integration from Garden Planner (`garden_planner`)
to Reap (`reap`) so it no longer shares a name with other projects. Home
Assistant treats it as a new integration:

1. Delete the Garden Planner integration in **Settings > Devices & services**.
2. Update in HACS and restart.
3. Add **Reap** and re-enter your plantings.
4. Delete any leftover Garden Planner tasks from your task list, and change
   dashboard cards from `custom:garden-planner-card` to `custom:reap-card`.

If a dashboard says `Custom element doesn't exist: reap-card` (for example when
dashboard resources are managed in YAML), add `/reap/reap-card.js` as a
**JavaScript module** under **Settings > Dashboards > Resources**.

### Setup options

Setup starts with the task list and a starting point for frost dates: Victoria
(the planting guide's dates), a USDA hardiness zone, or your own. Zones only
roughly predict frost dates, since they measure winter cold rather than season
length, so check the suggested dates against your local averages.

| Option | Victoria default | What it does |
| --- | --- | --- |
| Task list | Create a new Garden Tasks list | Pick an existing to-do list (any list that supports due dates works best) or let the planner create its own |
| Last spring frost | 03-06 | Average last frost |
| First fall frost | 11-16 | Average first frost |
| Last frost for warm crops | 04-01 | Tomatoes, peppers, squash and other frost-tender crops are timed from this instead. Useful where spring stays cool after the last frost, like coastal BC. Leave empty to use the last frost |
| Move all dates by | 0 days | Fine-tune for a warm (negative) or cold (positive) garden |
| Climate profile | Cool, slow spring | See below. Zone starting points suggest the fast-spring profile |
| Greenhouse weeks earlier in spring / later in fall | 4 / 4 | Widens every window for greenhouse plantings |
| Harden off days (beds / greenhouse) | 7 / 3 | Set to 0 to skip the task |
| Look-ahead days | 30 | Tasks are added to the list this many days before they're due, with their real due date, so long succession sowings don't flood it |

### Climate profiles

Planting charts from different regions show that frost dates alone don't
transfer: on the coast, spring is long and cool, so warm crops wait about a
month after the last frost; inland, spring warms fast and tomatoes go out one
to two weeks after it.

| Profile | Built from | Fits |
| --- | --- | --- |
| Cool, slow spring | South Coastal BC chart | Coastal BC, Pacific Northwest, UK, New Zealand |
| Spring warms fast | South Central BC and South Central Prairies charts, averaged | BC interior, Prairies, northern BC, most of the US and eastern Canada |
| Atlantic | Maritimes chart | Maritimes, Newfoundland |

Herbs, potato, tomatillo and a few crops missing from a regional chart are
estimated from their coastal timing, shifted by the typical difference for
crops that appear on both charts (`estimated_profiles` in `crops.json`).

All of these can be changed later under **Configure**.

## Dashboard card

The integration includes a card, loaded automatically (no separate install).
Reap adds its card to your dashboard resources when it starts. Edit a dashboard,
add a card and pick **Reap**, or use YAML:

```yaml
type: custom:reap-card
title: Garden              # optional
show_done: false           # optional: also list plantings with no open tasks
```

It lists your plantings with the crop's icon, how they're grown, and the next
task with its icon and date. The pencil edits a planting, the bin removes it,
and **Add planting** opens a form. The form fills in the crop's defaults,
**Preview dates** shows every task before you save, and **Save as the default
for this crop** remembers the method, repeat interval, number of sowings,
quantity and location for next time.

## Crop defaults

Each crop starts with sensible defaults: crops usually started indoors default
to indoor starts, and quick crops are set to repeat (radishes, lettuce,
arugula and spinach every 2 weeks; carrots, beets, cilantro and dill every 3;
peas, bush beans and corn a few times). Change them from the card or the
Configure menu with "Save as the default", or with the action:

```yaml
action: reap.set_crop_defaults
data:
  crop: carrot
  method: direct_bed
  succession_days: 14
  location: Bed 3
```

`clear: true` goes back to the built-in defaults. A planting can always
override them.

## Adding plantings

Go to **Settings > Devices & services > Reap > Configure** and pick
**Add a planting**:

1. Choose the crop.
2. Choose how it's grown (only the methods that crop supports are offered),
   and optionally a start date, repeat sowings, variety, quantity and location.
3. Check the list of dates, then submit.

**Remove plantings** and **Settings** are on the same menu.

You can also use the `reap.add_planting` action from Developer tools
> Actions, a script or a dashboard button.

```yaml
action: reap.add_planting
data:
  crop: carrot
  method: direct_bed
  succession_days: 7        # sow again every week
  succession_until: "2027-07-01"
  location: Bed 3
```

| Field | Notes |
| --- | --- |
| `crop` | Catalog key, such as `tomato`, `pepper`, `garlic` |
| `method` | `indoor_bed`, `indoor_greenhouse`, `direct_bed`, `direct_greenhouse`. Defaults to the crop's default method |
| `year` | Defaults to this year, or next year from September on |
| `season` | For crops with more than one window, such as `fall` for garlic or broad beans |
| `start_date` | Transplant date (indoor methods) or first sowing date (direct). Defaults to the start of the crop's window |
| `succession_days`, `succession_count`, `succession_until` | Repeat sowings |
| `variety`, `quantity`, `location`, `notes` | Shown on the tasks |

`reap.preview_planting` takes the same fields and returns the tasks
without saving anything. `reap.update_planting` takes a
`planting_id` plus any fields to change (an empty value clears a field). `reap.remove_planting` removes a planting
and its open tasks (completed ones stay on your list).

## How dates are worked out

- **Frost offsets**: each crop window is stored as offsets such as `L-31`
  (31 days before last frost) or `F-57` (57 days before first frost). Dates
  before July on the chart are measured from the last frost (April 1 on the
  chart), later ones from the first frost (November 16). Your frost dates and
  offset turn them back into calendar dates.

- **Indoor starts**: sow indoors = transplant date minus the crop's weeks
  indoors (tomato 7, pepper 10, onion and leek 10). Tomatoes, peppers,
  eggplant, tomatillos and artichokes get a pot-up task halfway.
- **Greenhouse**: every window opens 4 weeks earlier and closes 4 weeks later.
- **Harvest**: sowing date plus days to harvest, for the crop's harvest weeks.
  Fall garlic is harvested the next summer.
- **Ticking a task off**: the date you tick it is recorded. If it was 5 days
  late, the rest of that planting's tasks move 5 days later. Un-ticking undoes
  it. Deleting a task from the list means it won't be added back.

## Custom crops and varieties

```yaml
action: reap.add_crop
data:
  key: tomato_sungold
  name: Tomato, Sungold
  based_on: tomato
  days_to_harvest: 105
```

A new crop without `based_on` needs `windows`. Ranges can be your garden's
calendar dates (MM-DD), which are saved as offsets from your frost dates, or
offsets directly (`L-14`, `F+7`):

```yaml
  windows:
    - season: spring
      indoor: ["03-01", "04-15"]
      transplant: ["05-01", "06-15"]
```

Using a built-in key overrides that crop. `reap.list_crops` returns
every crop with its icon, methods, seasons and defaults.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.reap_next_task` | Next open task | due date, crop, method |
| `sensor.reap_tasks_due_this_week` | Count, including overdue | task list |
| `sensor.reap_overdue_tasks` | Count | task list |
| `sensor.reap_plantings` | Count | every planting with its full schedule |
| `todo.reap_garden_tasks` | Only when the planner makes its own list | |

Each crop has a Material Design icon (`mdi:carrot`, `mdi:chili-mild`,
`mdi:spa` for herbs and so on) and each kind of task has one too (`mdi:seed`
for sowing, `mdi:shovel` for transplanting, `mdi:basket` for harvest). The
next task sensor shows the crop's icon, and task attributes carry `icon` and
`crop_icon` for dashboards.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The catalog is generated from the chart transcription in
`scripts/build_catalog.py`: edit that file and run it to rebuild
`data/crops.json`.
