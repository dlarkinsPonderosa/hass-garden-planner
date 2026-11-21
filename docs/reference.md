# Reference

[Back to the README](../README.md)

## Entities

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.reap_next_task` | Next open task | due date, crop, method |
| `sensor.reap_tasks_due_this_week` | Count, including overdue | task list |
| `sensor.reap_overdue_tasks` | Count | task list |
| `sensor.reap_plantings` | Count | every planting with its next tasks, `current_location` and `current_locations` (where it is now), `active` (under way now) and `timeline` (phase date ranges); `southern` |
| `todo.reap_garden_tasks` | Only when the planner makes its own list | |

Each crop has a Material Design icon (`mdi:carrot`, `mdi:chili-mild`,
`mdi:spa` for herbs and so on) and each kind of task has one too (`mdi:seed`
for sowing, `mdi:shovel` for transplanting, `mdi:basket` for harvest). The
next task sensor shows the crop's icon, and task attributes carry `icon` and
`crop_icon` for dashboards.

## Actions

| Action | Does |
| --- | --- |
| `reap.add_planting`, `reap.add_plantings` | Add one or several plantings |
| `reap.preview_planting` | The tasks a planting would get, without saving |
| `reap.update_planting`, `reap.remove_planting` | Change or remove a planting |
| `reap.copy_plantings` | Copy a year's plantings to another year |
| `reap.set_crop_defaults` | Save a crop's default method, repeat, quantity, location and start location |
| `reap.add_crop`, `reap.list_crops`, `reap.reset_crop` | Custom crops and the catalog |
| `reap.add_location`, `reap.update_location`, `reap.remove_location`, `reap.list_locations` | Locations |
| `reap.log_watering` | Record a watering by hand |

Each one is described in Developer tools > Actions, and the guides show
examples: [plantings and crops](plantings.md), [locations](locations.md).

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
