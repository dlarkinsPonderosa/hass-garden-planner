# Setup and settings

[Back to the README](../README.md)

## Setup options

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

## Climate profiles

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

## Upgrading from Garden Planner (0.2.x)

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
