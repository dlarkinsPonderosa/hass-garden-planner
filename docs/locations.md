# Locations and watering

[Back to the README](../README.md)

## Setting up locations

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

## Starting indoors, then planting out

A planting started indoors can have two locations: **Start in** (a seedling
tray, a heat mat, a shelf under lights) and **Plant out to** (the bed or
greenhouse it ends up in). Both are on the planting's form when its method
starts indoors.

- Until you tick off its transplant task, the planting is in its start
  location. Ticking it off moves the planting to where it's planted out, and
  un-ticking moves it back.
- Everything that shows where a planting is follows this: the location on the
  Reap card, its moisture and light, the crops on the locations card, and
  the location written on each task (sowing, potting up and hardening off
  name the start location, transplanting and harvest name the bed).
- **Start in** is optional. Plan where a crop is going first, and add the tray
  when you actually sow it. Until then the planting shows where it's going.
- Plans change: edit the planting and pick another **Plant out to** at any
  time, before or after planting out. If you also change the method (say
  from greenhouse to beds), the tasks that aren't done yet are re-timed, and
  the form says so before you save.
- Repeat sowings can be in both places at once, such as "Seedling Tray and
  Garden": each sowing moves when its own transplant task is ticked off.
- Deleting a transplant task from your list, rather than ticking it off,
  counts as planted out once its due date has passed.
- The Locations list on the Reap card shows how many plantings use each
  location, planned ones included, and how many are there now. A location
  any planting uses can't be removed.
- The planner card's **By location** groups plantings by where they're going.

## Watering

Reap remembers when each location was last watered: when its valve or switch
turns on, and for how long it ran. This survives restarts. For beds watered by
hand, the **Watered** button on the locations card (or `reap.log_watering`)
records a watering now.

Actions: `reap.add_location`, `reap.update_location`, `reap.remove_location`,
`reap.list_locations` and `reap.log_watering`.

<img src="images/main-locations-light.png" alt="Locations on the Reap card" width="380">

To keep an eye on them, add the [locations card](cards.md#locations-card).
