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

The built-in catalog has 53 vegetables and 22 herbs. You can add your own crops
and varieties from the card, the Configure menu or an action.

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

Setup starts with the task list and a starting point for frost dates: a USDA
hardiness zone or your own dates. Zones only
roughly predict frost dates, since they measure winter cold rather than season
length, so check the suggested dates against your local averages.

| Option | Default | What it does |
| --- | --- | --- |
| Task list | Create a new Garden Tasks list | Pick an existing to-do list (any list that supports due dates works best) or let the planner create its own |
| Last spring frost | 04-20, or your zone's | Average last frost |
| First fall frost | 10-20, or your zone's | Average first frost |
| Last frost for warm crops | empty | Tomatoes, peppers, squash and other frost-tender crops are timed from this instead. Useful where spring stays cool for weeks after the last frost. Leave empty to use the last frost |
| Move all dates by | 0 days | Fine-tune for a warm (negative) or cold (positive) garden |
| Climate profile | Spring warms fast | See below |
| Greenhouse weeks earlier in spring / later in fall | 4 / 4 | Widens every window for greenhouse plantings |
| Harden off days (beds / greenhouse) | 7 / 3 | Set to 0 to skip the task |
| Look-ahead days | 30 | Tasks are added to the list this many days before they're due, with their real due date, so long succession sowings don't flood it |

### Climate profiles

Frost dates alone don't transfer between climates. Where spring is long and
cool, warm crops wait about a month after the last frost; where spring warms
fast, tomatoes go out one to two weeks after it. Pick the profile that sounds
most like your garden.

| Profile | Fits |
| --- | --- |
| Cool, slow spring | Mild maritime climates, such as the Pacific Northwest, the UK and New Zealand |
| Spring warms fast | Inland and continental climates |
| Cool, late spring with a long fall | Cold-water coasts, such as Atlantic Canada |

Some crops have no published timing for every profile. Those are estimated
from the cool-spring timing, shifted by the typical difference for crops that
have both (`estimated_profiles` in `crops.json`).

**Southern hemisphere:** enter your frost dates as usual (for example a last
frost of 09-15 and a first frost of 05-01). Reap uses your Home Assistant home
location to tell the hemisphere (or, without one, a first frost earlier in the
calendar than the last frost). Down south the season runs across the new year:
a planting's year is the year its spring falls in, and its fall tasks land in
the next calendar year.

**Changing settings with plantings in place:** some crops have different
seasons or methods in each climate profile. If a change in Settings would
leave a planting that can't be scheduled, Configure lists it first; save
again to keep the change. The card then marks that planting "Needs attention"
until you change its season or method, or remove it. Its items stay on your
list in the meantime.

All of these can be changed later under **Configure**.

## Dashboard card

The integration includes a card, loaded automatically (no separate install).
Reap adds its card to your dashboard resources when it starts. Edit a dashboard,
add a card and pick **Reap**, or use YAML:

```yaml
type: custom:reap-card
title: Garden          # optional
show_info: true        # details row: method, year, location, quantity
show_next: true        # next task row
show_sensors: true     # soil moisture and light of each planting's location
icon_size: 40          # crop icon size in pixels
editable: true         # show Add, Locations, edit and remove buttons
show_done: false       # also list plantings with no open tasks
planner_path: /lovelace/plan   # optional: adds a Plan button that opens this view
```

Every option is also in the card's visual editor. When a row is turned off the
rest centre vertically.

It lists your plantings with the crop's icon, how they're grown, and the next
task with its icon and date. The pencil edits a planting, the bin removes it,
and **Add planting** opens a form. The form fills in the crop's defaults,
**Preview dates** shows every task before you save, and **Save as the default
for this crop** remembers the method, repeat interval, number of sowings,
quantity and location for next time.

The card uses your theme's colours.

### Planner card

The planner card shows one growing year as a season chart: a row for each
planting, from starting indoors and planting out to harvest, across the
months. Pick **Reap planner** when adding a card, or:

```yaml
type: custom:reap-planner-card
title: Garden plan     # optional
group_by: date         # or crop, or location
max_height: 480        # chart height in pixels before it scrolls; 0 for no limit
editable: true         # add, edit, remove and copy
```

- The arrows change year. A year runs January to December, or July to June
  in the southern hemisphere ("2027–28").
- Plantings from another year that are still in the ground show faded, such
  as fall garlic in the spring after it was planted. A planting that runs
  into the next year has an arrow at the right edge.
- Click a planting to see its dates under it, with **Edit** and **Remove**.
- **Copy to 2028** copies the year's plantings to the next one with the same
  settings. Untick anything you're not growing again.

It can sit on the same dashboard as the Reap card. To keep the main dashboard
simple, put it on a [subview](https://www.home-assistant.io/dashboards/views/#subview)
instead and set the Reap card's `planner_path` to that view's path, such as
`/lovelace/plan`. The Reap card then has a **Plan** button that opens it.

```yaml
views:
  - title: Garden plan
    path: plan
    subview: true
    cards:
      - type: custom:reap-planner-card
```

Its colours follow your theme in light and dark mode. Themes can set
`reap-indoor-color`, `reap-sow-color`, `reap-harvest-color`,
`reap-grow-color` and `reap-winter-color`, `reap-spring-color`,
`reap-summer-color`, `reap-fall-color` to change them.

## Locations

Plantings pick their location from a list. A new install starts with
**Seedling Tray**, **Garden** and **Greenhouse**, and any locations your
plantings already used are added on upgrade. Open **Locations** on the card to
add, rename or remove them. Renaming moves the plantings with it, and a
location in use can't be removed.

Each location can have, all optional:

- a soil moisture sensor,
- a light (a light, switch or input boolean, such as grow lights),
- a watering valve or switch (a `valve`, `switch` or `input_boolean`),
- a camera.

The Reap card shows moisture and the light next to each planting in that
location: moisture in % in green above 30%, yellow from 15 to 30% and red below
15%, and a bulb icon for the light's state. Tap either for its details. The
card options `moisture_good` and `moisture_low` change the 30 and 15.

Reap remembers when each location was last watered: when its valve or switch
turns on, and for how long it ran. This survives restarts. For beds watered by
hand, the **Watered** button on the locations card (or `reap.log_watering`)
records a watering now.

Actions: `reap.add_location`, `reap.update_location`, `reap.remove_location`,
`reap.list_locations` and `reap.log_watering`.

### Locations card

A read-only card for keeping an eye on your locations: one tile each with soil
moisture, when it was last watered, buttons to start or stop watering (starting
asks first) or log a watering by hand, the light switch, a camera button, and
icons of what's growing there. Pick **Reap locations** when adding a card, or:

```yaml
type: custom:reap-locations-card
title: Garden locations   # optional
locations: []             # names to show, in this order; empty shows all
show_moisture: true
show_last_watered: true
show_watering: true
show_light: true
show_camera: true
show_snapshot: false      # a camera picture on the tile, refreshed every minute
show_plantings: true      # icons of the crops growing there
moisture_good: 30         # green above this %
moisture_low: 15          # red below this %
```

Anything a location doesn't have is left off its tile. Locations are added
and edited on the Reap card.

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
| `year` | Defaults to the next season the crop can still be sown in: this year if its window hasn't ended, otherwise next year |
| `season` | For crops with more than one window, such as `fall` for garlic or broad beans |
| `start_date` | Transplant date (indoor methods) or first sowing date (direct). Defaults to the start of the crop's window |
| `succession_days`, `succession_count`, `succession_until` | Repeat sowings |
| `variety`, `quantity`, `location`, `notes` | Shown on the tasks |

`reap.preview_planting` takes the same fields and returns the tasks
without saving anything. `reap.update_planting` takes a
`planting_id` plus any fields to change (an empty value clears a field). `reap.remove_planting` removes a planting
and its open tasks (completed ones stay on your list).

### Several at once

On the card, **Add planting** has two tabs:

- **One crop**: under the variety, **Add another variety** makes one planting
  per variety (Sungold, Brandywine, San Marzano...), each with its own
  quantity and the same method, dates and location.
- **Several crops**: tick the crops you want. Each one starts from its own
  defaults (method, repeat, quantity, location). A year, method, location or
  notes set on the form apply to all of them; a method is only used for crops
  that can be grown that way.

**Copy to** on the [planner card](#planner-card) copies a year's plantings to
another year with the same settings, moving start and repeat-until dates with
them. Plantings already planned for the new year start unticked.

The same as actions:

```yaml
action: reap.add_plantings
data:
  plantings:
    - crop: lettuce
    - crop: tomato
      variety: Sungold
      location: Greenhouse
---
action: reap.copy_plantings
data:
  from_year: 2026      # to_year defaults to the next year
```

`add_plantings` adds all of them, or none if one can't be scheduled. Set
`use_defaults: false` to skip the crops' saved defaults.

## How dates are worked out

- **Frost offsets**: each crop window is stored as offsets such as `L-31`
  (31 days before last frost) or `F-57` (57 days before first frost). Spring
  steps are measured from the last frost and late-season steps from the first
  frost. Your frost dates and offset turn them back into calendar dates.

- **Indoor starts**: sow indoors = transplant date minus the crop's weeks
  indoors (tomato 7, pepper 10, onion and leek 10). Tomatoes, peppers,
  eggplant, tomatillos and artichokes get a pot-up task halfway.
- **Greenhouse**: every window opens 4 weeks earlier and closes 4 weeks later.
- **Harvest**: sowing date plus days to harvest, for the crop's harvest weeks.
  Crops that overwinter (fall garlic and fava, overwintering onion and
  cabbage) are harvested the next spring or summer, whenever they went in.
- **Ticking a task off**: the date you tick it is recorded. If it was 5 days
  late, the rest of that planting's tasks move 5 days later. Un-ticking undoes
  it. Deleting a task from the list means it won't be added back.
- **Notes on a task**: Reap keeps each item's description up to date (quantity,
  location, notes) down to its `reap:` line. Anything you type below that line
  is yours and is kept.

## Custom crops and varieties

To add a crop or variety that isn't built in, open **Crops** on the card and
choose **Add crop**, or go to **Settings > Devices & services > Reap >
Configure > Add a crop or variety**. Give it a name, a category and an icon,
then either:

- **copy timing from** an existing crop (best for a variety, such as a
  particular tomato), changing only what differs, like days to harvest, or
- enter the dates you'd usually start it indoors, transplant it, or sow it
  directly in spring or fall in your garden.

Dates you enter are saved relative to your frost dates, so they follow any
later change to your settings.

The built-in crops are just a starting list. Every crop, built-in or your own,
can be edited from the card, and removed once no planting uses it. Edited
built-in crops have an undo button that puts back the original, and removed
ones are listed under **Removed crops** with a **Restore** button
(`reap.reset_crop` does the same).

The same is available as an action:

```yaml
action: reap.add_crop
data:
  key: tomato_sungold
  name: Tomato, Sungold
  based_on: tomato
  days_to_harvest: 105
  icon: mdi:fruit-cherries
```

A crop without `based_on` needs `windows`. Ranges can be calendar dates
(MM-DD) or offsets from your frost dates (`L-14`, `F+7`):

```yaml
  windows:
    - season: spring
      indoor: ["03-01", "04-15"]
      transplant: ["05-01", "06-15"]
```

Using a built-in key overrides that crop. `reap.list_crops` returns every crop
with its icon, category, methods, seasons and defaults.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.reap_next_task` | Next open task | due date, crop, method |
| `sensor.reap_tasks_due_this_week` | Count, including overdue | task list |
| `sensor.reap_overdue_tasks` | Count | task list |
| `sensor.reap_plantings` | Count | every planting with its next tasks and `timeline` (phase date ranges); `southern` |
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
`data/crops.json`. The tests check that the two match
(`python scripts/build_catalog.py --check`), so edit the script rather than
the JSON.

Service error messages come from the planner in English. The
`exceptions` entries in `strings.json` pass that text through (`{error}`), so
other languages would need the planner's messages translated first.

Releases: bump `version` in `manifest.json` (it also busts the card's cache).
When that reaches `main`, the Release workflow tags it (`v0.4.3`) and
publishes a GitHub release, so HACS shows real version numbers.
