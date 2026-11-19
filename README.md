# Garden Planner for Home Assistant

Turns a list of crops into dated garden tasks on a Home Assistant to-do list:
sowing indoors, potting up, hardening off, transplanting, direct sowing,
covering and harvest. It handles three ways of growing (indoor starts under
lights, beds, heated greenhouse), repeat sowings such as carrots every week,
and moves later tasks when you tick one off early or late.

The built-in crop catalog is transcribed from the
*South Coastal BC Vegetable Planting Guide* (49 crops), plus potato, tomatillo,
cilantro, dill and Italian parsley. You can add your own crops and varieties.

## Install

1. In HACS, open the three-dot menu, choose **Custom repositories**, add
   `https://github.com/dlarkinsPonderosa/hass-garden-planner` as an
   **Integration**, then download **Garden Planner**.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration > Garden Planner**.

### Setup options

| Option | Default | What it does |
| --- | --- | --- |
| Task list | Create a new Garden Tasks list | Pick an existing to-do list (any list that supports due dates works best) or let the planner create its own |
| Last spring frost | 03-06 | Victoria, from the planting guide |
| First fall frost | 11-16 | Victoria, from the planting guide |
| Shift the chart's dates | On | Moves spring dates by how far your last frost is from the chart's April 1 baseline (26 days earlier for Victoria) and fall dates by your first frost |
| Also shift frost-tender crops in beds | Off | Tomatoes, peppers, squash and other warm crops keep the chart's bed dates unless this is on |
| Greenhouse weeks earlier in spring / later in fall | 4 / 4 | Widens every window for greenhouse plantings |
| Harden off days (beds / greenhouse) | 7 / 3 | Set to 0 to skip the task |
| Look-ahead days | 30 | Tasks are added to the list when they are this close, so long succession sowings don't flood it |

All of these can be changed later under **Configure**.

## Adding plantings

Use the `garden_planner.add_planting` action (Developer tools > Actions, a
script, or a dashboard button). The crop field is a dropdown of the catalog.

```yaml
action: garden_planner.add_planting
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
| `method` | `indoor_bed`, `indoor_greenhouse`, `direct_bed`, `direct_greenhouse` |
| `year` | Defaults to this year, or next year from September on |
| `season` | For crops with more than one window, such as `fall` for garlic or broad beans |
| `start_date` | Transplant date (indoor methods) or first sowing date (direct). Defaults to the start of the crop's window |
| `succession_days`, `succession_count`, `succession_until` | Repeat sowings |
| `variety`, `quantity`, `location`, `notes` | Shown on the tasks |

`garden_planner.preview_planting` takes the same fields and returns the tasks
without saving anything. `garden_planner.remove_planting` removes a planting
and its open tasks (completed ones stay on your list).

## How dates are worked out

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
action: garden_planner.add_crop
data:
  key: tomato_sungold
  name: Tomato, Sungold
  based_on: tomato
  days_to_harvest: 105
```

A new crop without `based_on` needs `windows`, using month-day ranges:

```yaml
  windows:
    - season: spring
      indoor: ["03-01", "04-15"]
      transplant: ["05-01", "06-15"]
```

Using a built-in key overrides that crop. `garden_planner.list_crops` returns
the whole catalog.

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.garden_planner_next_task` | Next open task | due date, crop, method |
| `sensor.garden_planner_tasks_due_this_week` | Count, including overdue | task list |
| `sensor.garden_planner_overdue_tasks` | Count | task list |
| `sensor.garden_planner_plantings` | Count | every planting with its full schedule |
| `todo.garden_planner_garden_tasks` | Only when the planner makes its own list | |

## Development

```bash
pip install -r requirements_test.txt
pytest
```
