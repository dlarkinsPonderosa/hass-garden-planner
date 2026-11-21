/*
 * Reap card: lists plantings with their icons and next task, and
 * adds, edits and removes them through the reap actions.
 *
 * type: custom:reap-card
 * entity: sensor.reap_plantings   # optional
 * title: Garden                   # optional
 * show_done: false                # also list plantings with no open tasks
 * show_info: true                 # second row: method, year, location...
 * show_next: true                 # third row: the next task
 * show_sensors: true              # soil moisture and light of the location
 * icon_size: 40                   # crop icon size in pixels
 * editable: true                  # show add, edit and remove buttons
 * planner_path: /lovelace/plan    # optional: a Plan button that opens this view
 * moisture_good: 30               # soil moisture % above this is green
 * moisture_low: 15                # below this is red; in between is yellow
 *
 * type: custom:reap-planner-card    # the season chart, defined further down
 *
 * type: custom:reap-locations-card  # read-only location tiles, defined further down
 * group_by: date                    # or crop, or location
 * max_height: 480                   # chart height in px before it scrolls; 0 = no limit
 */

const CARD_DEFAULTS = {
  entity: "sensor.reap_plantings",
  show_done: false,
  show_info: true,
  show_next: true,
  show_sensors: true,
  icon_size: 40,
  editable: true,
  planner_path: "",
  moisture_good: 30,
  moisture_low: 15,
};

const METHOD_LABELS = {
  indoor_bed: "Start indoors, transplant to beds",
  indoor_greenhouse: "Start indoors, transplant to greenhouse",
  direct_bed: "Direct sow in beds",
  direct_greenhouse: "Direct sow in greenhouse",
};
const METHOD_ICONS = {
  indoor_bed: "mdi:home-outline",
  indoor_greenhouse: "mdi:greenhouse",
  direct_bed: "mdi:shovel",
  direct_greenhouse: "mdi:greenhouse",
};
const DEFAULT_KEYS = ["method", "succession_days", "succession_count", "quantity", "location"];
const FIELDS = [
  "method", "season", "year", "start_date", "succession_days",
  "succession_count", "succession_until", "variety", "quantity", "location", "notes",
];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key in el && key !== "list") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function icon(name, cls = "") {
  return h("ha-icon", { icon: name, class: cls });
}

// Dates follow the language set in Home Assistant, not the browser's.
let LOCALE;

function shortDate(iso, withYear = false) {
  const [y, m, d] = iso.split("-").map(Number);
  const opts = withYear ? { month: "short", day: "numeric", year: "numeric" } : { month: "short", day: "numeric" };
  try {
    return new Date(y, m - 1, d).toLocaleDateString(LOCALE, opts);
  } catch (err) {
    return new Date(y, m - 1, d).toLocaleDateString(undefined, opts);
  }
}

// Green above moisture_good, yellow down to moisture_low, red below that.
function moistureLevel(value, config = {}) {
  const good = Number.isFinite(Number(config.moisture_good)) ? Number(config.moisture_good) : 30;
  const low = Number.isFinite(Number(config.moisture_low)) ? Number(config.moisture_low) : 15;
  if (value > good) return "good";
  if (value >= low) return "low";
  return "dry";
}

const LIGHT_DOMAINS = ["light.", "switch.", "input_boolean."];
const WATER_DOMAINS = ["valve.", "switch.", "input_boolean."];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CATEGORIES = [["vegetable", "Vegetable"], ["herb", "Herb"], ["fruit", "Fruit"], ["flower", "Flower"]];
// Crop form date fields: [form key, window season, window kind, end of range?]
const CROP_DATES = [
  ["spring_indoor", "spring", "indoor"],
  ["spring_transplant", "spring", "transplant"],
  ["spring_direct", "spring", "direct"],
  ["summer_indoor", "summer", "indoor"],
  ["summer_transplant", "summer", "transplant"],
  ["summer_direct", "summer", "direct"],
  ["fall_indoor", "fall", "indoor"],
  ["fall_transplant", "fall", "transplant"],
  ["fall_direct", "fall", "direct"],
];
const CROP_SEASONS = ["spring", "summer", "fall"];

// What makes two plantings "the same" when planning a year again.
function sameKey(p) {
  return [p.crop, p.method, p.season || "", p.variety || "", (p.location || "").toLowerCase(),
    (p.start_date || "").slice(5)].join("|");
}

// Go to a dashboard path the way Home Assistant's own links do.
function navigate(path) {
  window.history.pushState(null, "", path.startsWith("/") ? path : `/${path}`);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

function slug(text) {
  return text.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "crop";
}


class ReapCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...CARD_DEFAULTS, ...config };
    this._mode = null; // null | "add" | "edit" | "locations" | "location" | "crops" | "crop"
    this._form = {};
    this._editing = null;
    this._confirmDelete = null;
    this._preview = null;
    this._error = null;
    this._busy = false;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    LOCALE = (hass.locale && hass.locale.language) || hass.language || undefined;
    // While list_crops fails, wait longer between tries instead of asking on
    // every state change in the house.
    if (!this._crops && !this._loadingCrops && !(this._cropsRetryAt > Date.now())) this._loadCrops();
    // Only redraw when something shown changes, so typing in a form isn't interrupted.
    if (!this._mode && (!old || this._watched().some((id) => old.states[id] !== hass.states[id]))) {
      this._render();
    }
  }

  _watched() {
    const ids = [this._config.entity];
    if (this._config.show_sensors) {
      for (const loc of this._locations()) {
        if (loc.soil_sensor) ids.push(loc.soil_sensor);
        if (loc.light) ids.push(loc.light);
      }
    }
    return ids;
  }

  static getConfigElement() {
    return document.createElement("reap-card-editor");
  }

  getCardSize() {
    return 3 + this._plantings().length;
  }

  static getStubConfig() {
    return { entity: "sensor.reap_plantings" };
  }

  async _call(service, data, response = false) {
    const msg = { type: "call_service", domain: "reap", service, service_data: data };
    if (response) msg.return_response = true;
    const result = await this._hass.connection.sendMessagePromise(msg);
    return response ? result.response : result;
  }

  async _loadCrops() {
    this._loadingCrops = true;
    try {
      const res = await this._call("list_crops", {}, true);
      this._crops = res.crops;
      this._hiddenCrops = res.hidden || [];
      this._cropsDelay = 0;
      this._cropsRetryAt = 0;
      if (this._cropsError) { this._error = null; this._cropsError = false; }
    } catch (err) {
      this._cropsDelay = Math.min((this._cropsDelay || 2500) * 2, 300000);
      this._cropsRetryAt = Date.now() + this._cropsDelay;
      this._error = `Couldn't load the crop list: ${err.message || err}`;
      this._cropsError = true;
    }
    this._loadingCrops = false;
    this._render();
  }

  _plantings() {
    const state = this._hass && this._hass.states[this._config.entity];
    if (!state) return [];
    return state.attributes.plantings || [];
  }

  _locations() {
    const state = this._hass && this._config && this._hass.states[this._config.entity];
    return (state && state.attributes.locations) || [];
  }

  _location(name) {
    if (!name) return null;
    const folded = name.toLowerCase();
    return this._locations().find((l) => l.name.toLowerCase() === folded) || null;
  }

  _crop(key) {
    return (this._crops || []).find((c) => c.key === key);
  }

  // ----- actions -----

  _startAdd() {
    const first = (this._crops || [])[0];
    this._mode = "add";
    this._editing = null;
    // No year: Reap picks the next season the crop can still be sown in.
    this._form = { year: "", bulk: false, picked: [], varieties: [{ variety: "", quantity: "" }] };
    if (first) this._pickCrop(first.key, false);
    this._preview = null;
    this._error = null;
    this._render();
  }

  _startEdit(planting) {
    this._mode = "edit";
    this._editing = planting.id;
    this._form = { crop: planting.crop };
    for (const key of FIELDS) {
      if (planting[key] !== null && planting[key] !== undefined) this._form[key] = planting[key];
    }
    this._preview = null;
    this._error = null;
    this._render();
  }

  _pickCrop(key, render = true) {
    const crop = this._crop(key);
    this._form.crop = key;
    if (crop && this._mode === "add") {
      // Start from this crop's defaults.
      for (const k of DEFAULT_KEYS) delete this._form[k];
      Object.assign(this._form, crop.defaults || {});
      if (this._form.varieties) {
        for (const row of this._form.varieties) row.quantity = this._form.quantity || "";
      }
    }
    if (crop) {
      if (!crop.methods.includes(this._form.method)) this._form.method = crop.methods[0];
      if (crop.seasons.length < 2) delete this._form.season;
      else if (!crop.seasons.includes(this._form.season)) this._form.season = crop.seasons[0];
    }
    this._preview = null;
    if (render) this._render();
  }

  _payload() {
    const data = { crop: this._form.crop };
    for (const key of FIELDS) {
      let value = this._form[key];
      if (value === undefined) continue;
      if (typeof value === "string") value = value.trim();
      if (["year", "succession_days", "succession_count"].includes(key) && value !== "") {
        value = Number(value);
      }
      if (this._mode === "add" && (value === "" || value === null)) continue;
      data[key] = value === null ? "" : value;
    }
    return data;
  }

  async _doPreview() {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const data = this._payload();
      const row = (this._form.varieties || [])[0];
      if (row) Object.assign(data, { variety: row.variety.trim(), quantity: row.quantity.trim() });
      for (const key of Object.keys(data)) if (data[key] === "") delete data[key];
      if (data.succession_days === 0) delete data.succession_days;
      const res = await this._call("preview_planting", data, true);
      this._preview = res.tasks;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  async _save() {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const payload = this._payload();
      const saveDefaults = this._form.save_defaults;
      if (this._mode === "add") {
        // One planting per variety row, all with the same settings.
        const rows = (this._form.varieties || []).map((r) => ({ variety: r.variety.trim(), quantity: r.quantity.trim() }));
        const used = rows.filter((r) => r.variety || r.quantity);
        // The rows hold the quantity: an emptied one means no quantity.
        delete payload.quantity;
        if (used.length <= 1) {
          const row = used[0] || {};
          if (row.variety) payload.variety = row.variety;
          if (row.quantity) payload.quantity = row.quantity;
          await this._call("add_planting", payload);
        } else {
          if (used.some((r) => !r.variety)) throw new Error("Give each variety a name, or remove the empty row.");
          const names = used.map((r) => r.variety.toLowerCase());
          if (new Set(names).size < names.length) throw new Error("Each variety is listed once; two rows have the same name.");
          const plantings = used.map((r) => {
            const one = { ...payload, variety: r.variety };
            if (r.quantity) one.quantity = r.quantity;
            return one;
          });
          await this._call("add_plantings", { plantings, use_defaults: false });
        }
        if (used[0] && used[0].quantity) payload.quantity = used[0].quantity;
      } else {
        await this._call("update_planting", { planting_id: this._editing, ...payload });
      }
      // The planting is saved: close the form, so pressing Add again can't
      // make a second one, even if saving the defaults fails below.
      this._mode = null;
      this._form = {};
      this._preview = null;
      if (saveDefaults) {
        const defaults = { crop: payload.crop };
        for (const k of DEFAULT_KEYS) {
          if (payload[k] !== undefined && payload[k] !== "") defaults[k] = payload[k];
        }
        try {
          await this._call("set_crop_defaults", defaults);
          await this._loadCrops();
        } catch (err) {
          this._error = `The planting was saved, but its defaults weren't: ${err.message || err}`;
        }
      }
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  // ----- several crops at once -----

  async _saveBulk() {
    const f = this._form;
    const picked = f.picked || [];
    if (!picked.length) {
      this._error = "Tick the crops to add.";
      this._render();
      return;
    }
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const plantings = picked.map((key) => {
        const crop = this._crop(key);
        const one = { crop: key };
        if (f.year !== "" && f.year !== undefined) one.year = Number(f.year);
        if (f.bulk_method && crop && crop.methods.includes(f.bulk_method)) one.method = f.bulk_method;
        if (f.location) one.location = f.location;
        if ((f.notes || "").trim()) one.notes = f.notes.trim();
        return one;
      });
      await this._call("add_plantings", { plantings, use_defaults: true });
      this._mode = null;
      this._form = {};
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  // ----- copy a year -----

  _years() {
    return [...new Set(this._plantings().map((p) => p.year))].sort((a, b) => b - a);
  }

  _startCopy(fromYear, toYear) {
    const years = this._years();
    const thisYear = new Date().getFullYear();
    const from = fromYear || years.find((y) => y <= thisYear) || years[years.length - 1];
    this._mode = "copy";
    this._form = { from_year: from, to_year: toYear || Math.max(from + 1, thisYear) };
    this._pickCopy();
    this._error = null;
    this._notice = null;
    this._render();
  }

  // Tick every planting of the year, except ones already planned for the
  // target year.
  _pickCopy() {
    const f = this._form;
    // Each planting already planned covers one, so a March and a June block of
    // the same crop are told apart by their start date.
    const planned = {};
    for (const p of this._plantings().filter((p) => p.year === Number(f.to_year))) {
      planned[sameKey(p)] = (planned[sameKey(p)] || 0) + 1;
    }
    f.copy = {};
    f.planned = new Set();
    for (const p of this._plantings().filter((p) => p.year === Number(f.from_year))) {
      const key = sameKey(p);
      if (planned[key]) {
        planned[key] -= 1;
        f.planned.add(p.id);
      }
      f.copy[p.id] = !f.planned.has(p.id);
    }
  }

  async _saveCopy() {
    const f = this._form;
    const ids = Object.keys(f.copy || {}).filter((id) => f.copy[id]);
    if (!ids.length) {
      this._error = "Tick the plantings to copy.";
      this._render();
      return;
    }
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const res = await this._call("copy_plantings", {
        from_year: Number(f.from_year), to_year: Number(f.to_year), planting_ids: ids,
      }, true);
      const skipped = res.skipped || [];
      this._mode = null;
      this._form = {};
      this._copied(Number(f.to_year));
      if (skipped.length) {
        this._notice = `Copied ${res.planting_ids.length}. Not copied: ${skipped.map((s) => `${s.name} (${s.reason})`).join("; ")}`;
      }
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  _renderCopy() {
    const f = this._form;
    const wrap = h("div", { class: "form" });
    wrap.append(h("div", { class: "form-title" }, icon("mdi:calendar-sync"), "Plan a year again"));
    wrap.append(h("p", { class: "muted small" },
      "Copies plantings with the same settings to another year. Dates move with them. Ones already planned for that year start unticked."));
    const years = this._years();
    const yearSelect = (key, label, options) => h("label", { class: "field" }, h("span", {}, label),
      h("select", {
        onchange: (e) => {
          f[key] = Number(e.target.value);
          if (key === "from_year") f.to_year = Math.max(f.from_year + 1, new Date().getFullYear());
          this._pickCopy();
          this._render();
        },
      }, options.map((y) => h("option", { value: y, selected: Number(f[key]) === y }, String(y)))));
    // Last year on (a southern season can still be running), up to two
    // years past the latest. Reap skips plantings whose sowing time is over.
    const toYears = [];
    const thisYear = new Date().getFullYear();
    for (let y = thisYear - 1; y <= Math.max(...years, thisYear) + 2; y++) {
      if (y !== Number(f.from_year)) toYears.push(y);
    }
    wrap.append(h("div", { class: "grid" },
      yearSelect("from_year", "Copy from", years),
      yearSelect("to_year", "To", toYears)));
    const list = h("div", { class: "list picks" });
    const source = this._plantings().filter((p) => p.year === Number(f.from_year));
    if (!source.length) list.append(h("p", { class: "muted" }, "No plantings in that year."));
    for (const p of source) {
      const name = p.variety ? `${p.crop_name} (${p.variety})` : p.crop_name;
      const extra = [METHOD_LABELS[p.method] || p.method, p.season && p.season !== "spring" ? p.season : null,
        p.location, f.planned && f.planned.has(p.id) ? `already planned for ${f.to_year}` : null].filter(Boolean).join(" · ");
      list.append(h("label", { class: "pick" },
        h("input", { type: "checkbox", checked: !!f.copy[p.id], onchange: (e) => { f.copy[p.id] = e.target.checked; this._renderCount(); } }),
        icon(p.icon || "mdi:sprout"),
        h("span", { class: "info" }, h("span", { class: "name" }, name), h("span", { class: "muted small" }, extra))));
    }
    wrap.append(list);
    this._countBtn = h("button", { class: "primary", disabled: this._busy, onclick: () => this._saveCopy() });
    this._countLabel = (n) => [icon("mdi:content-copy"), `Copy ${n} planting${n === 1 ? "" : "s"}`];
    this._countOf = () => Object.values(f.copy || {}).filter(Boolean).length;
    this._renderCount();
    wrap.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Cancel"), this._countBtn));
    return wrap;
  }

  // The planner card shows the year copied to.
  _copied(_year) {}

  _style() {
    return STYLE;
  }

  _defaultTitle() {
    return "Garden";
  }

  _renderCount() {
    if (!this._countBtn) return;
    this._countBtn.replaceChildren(...this._countLabel(this._countOf()));
  }

  _renderBulk(form) {
    const f = this._form;
    const all = this._crops || [];
    f.picked = f.picked || [];
    form.append(h("p", { class: "muted small" },
      "Tick the crops to add. Each one uses its own defaults (method, repeat, quantity and location). Anything you set below applies to all of them."));
    const filter = h("input", {
      type: "search", placeholder: `Search ${all.length} crops`, class: "search", value: this._bulkFilter || "",
    });
    const list = h("div", { class: "list picks" });
    const rows = [];
    for (const c of all) {
      const method = (c.defaults && c.defaults.method) || c.methods[0];
      const row = h("label", { class: "pick" },
        h("input", {
          type: "checkbox", checked: f.picked.includes(c.key),
          onchange: (e) => {
            f.picked = e.target.checked ? [...f.picked, c.key] : f.picked.filter((k) => k !== c.key);
            this._renderCount();
          },
        }),
        icon(c.icon || "mdi:sprout"),
        h("span", { class: "info" }, h("span", { class: "name" }, c.name),
          h("span", { class: "muted small" }, METHOD_LABELS[method] || method || "")));
      row.dataset.name = c.name.toLowerCase();
      rows.push(row);
      list.append(row);
    }
    const applyFilter = () => {
      const q = (this._bulkFilter || "").trim().toLowerCase();
      for (const row of rows) row.hidden = !!q && !row.dataset.name.includes(q) && !row.querySelector("input").checked;
    };
    filter.addEventListener("input", (e) => { this._bulkFilter = e.target.value; applyFilter(); });
    applyFilter();
    form.append(filter, list);
    const names = this._locations().map((l) => [l.name, l.name]);
    form.append(h("div", { class: "grid" },
      this._input("year", "Year", "number", { min: 2000, max: 2100, placeholder: "Next season" }),
      this._select("bulk_method", "Method", [["", "Each crop's default"],
        ...Object.entries(METHOD_LABELS).map(([k, v]) => [k, `${v} (where it can be)`])]),
      this._select("location", "Location", [["", "Each crop's default"], ...names])));
    form.append(this._input("notes", "Notes"));
    this._countBtn = h("button", { class: "primary", disabled: this._busy, onclick: () => this._saveBulk() });
    this._countLabel = (n) => [icon("mdi:plus"), `Add ${n} planting${n === 1 ? "" : "s"}`];
    this._countOf = () => (f.picked || []).length;
    this._renderCount();
    form.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Cancel"), this._countBtn));
    return form;
  }

  _renderVarieties() {
    const f = this._form;
    const wrap = h("div", { class: "varieties" });
    wrap.append(h("span", { class: "field-label" }, f.varieties.length > 1 ? "Varieties (one planting each)" : "Variety"));
    f.varieties.forEach((row, i) => {
      const variety = h("input", { type: "text", value: row.variety, placeholder: i ? "Another variety" : "Sungold",
        oninput: (e) => { row.variety = e.target.value; this._preview = null; } });
      const quantity = h("input", { type: "text", value: row.quantity, placeholder: "Quantity, such as 6 cells",
        oninput: (e) => { row.quantity = e.target.value; } });
      wrap.append(h("div", { class: "variety" }, variety, quantity,
        f.varieties.length > 1
          ? h("button", { class: "icon-btn", title: "Remove", onclick: () => { f.varieties.splice(i, 1); this._render(); } }, icon("mdi:close"))
          : null));
    });
    wrap.append(h("div", {},
      h("button", { onclick: () => { f.varieties.push({ variety: "", quantity: f.varieties[0].quantity || "" }); this._render(); } },
        icon("mdi:plus"), "Add another variety")));
    return wrap;
  }

  async _delete(id) {
    this._busy = true;
    try {
      await this._call("remove_planting", { planting_id: id });
      this._confirmDelete = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  _openLocations() {
    this._mode = "locations";
    this._error = null;
    this._confirmDelete = null;
    this._render();
  }

  _startLocation(loc) {
    this._ensurePickers();
    this._mode = "location";
    this._editing = loc ? loc.id : null;
    this._form = loc
      ? { name: loc.name, soil_sensor: loc.soil_sensor || "", light: loc.light || "",
        camera: loc.camera || "", water: loc.water || "" }
      : { name: "", soil_sensor: "", light: "", camera: "", water: "" };
    this._error = null;
    this._render();
  }

  async _saveLocation() {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const data = {
        name: (this._form.name || "").trim(),
        soil_sensor: this._form.soil_sensor || "",
        light: this._form.light || "",
        camera: this._form.camera || "",
        water: this._form.water || "",
      };
      if (this._editing) await this._call("update_location", { location_id: this._editing, ...data });
      else await this._call("add_location", data);
      this._mode = "locations";
      this._form = {};
      this._editing = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  async _deleteLocation(id) {
    this._busy = true;
    try {
      await this._call("remove_location", { location_id: id });
      this._confirmDelete = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  _openCrops() {
    this._mode = "crops";
    this._error = null;
    this._confirmDelete = null;
    this._render();
  }

  _startCrop(crop) {
    this._mode = "crop";
    this._editing = crop ? crop.key : null;
    this._form = crop
      ? {
        name: crop.name, category: crop.category || "vegetable", icon: crop.icon || "",
        days_to_harvest: crop.days_to_harvest, harvest_weeks: crop.harvest_weeks,
        weeks_indoor: crop.weeks_indoor || "", frost_tender: crop.frost_tender, planted: !!crop.planted, perennial: crop.perennial,
        notes: crop.notes || "", based_on: "",
      }
      : { name: "", category: "vegetable", icon: "", based_on: "", frost_tender: false, planted: false, perennial: false };
    // Windows the form can't show (another season, or a second window of a
    // season) are sent back unchanged, so editing never drops them.
    this._extraWindows = [];
    if (crop) {
      const seen = new Set();
      for (const w of crop.windows || []) {
        if (!CROP_SEASONS.includes(w.season) || seen.has(w.season)) {
          this._extraWindows.push(w);
          continue;
        }
        seen.add(w.season);
        for (const kind of ["indoor", "transplant", "direct"]) {
          const key = `${w.season}_${kind}`;
          if (w[kind]) {
            this._form[`${key}_from`] = w[kind][0];
            this._form[`${key}_to`] = w[kind][1];
          }
        }
      }
    }
    this._error = null;
    this._render();
  }

  _cropPayload() {
    const f = this._form;
    const name = (f.name || "").trim();
    if (!name) throw new Error("Give the crop a name.");
    let key = this._editing;
    if (!key) {
      const taken = new Set([...(this._crops || []), ...(this._hiddenCrops || [])].map((c) => c.key));
      const base = slug(name);
      key = base;
      for (let n = 2; taken.has(key); n++) key = `${base}_${n}`;
    }
    const data = { key, name, category: f.category || "vegetable", frost_tender: !!f.frost_tender, planted: !!f.planted, perennial: !!f.perennial };
    if ((f.icon || "").trim()) data.icon = f.icon.trim();
    if (f.based_on) data.based_on = f.based_on;
    for (const k of ["days_to_harvest", "harvest_weeks", "weeks_indoor"]) {
      if (f[k] !== undefined && f[k] !== null && f[k] !== "") data[k] = Number(f[k]);
    }
    if ((f.notes || "").trim()) data.notes = f.notes.trim();
    const windows = {};
    for (const [field, season, kind] of CROP_DATES) {
      const from = f[`${field}_from`], to = f[`${field}_to`];
      if (!from && !to) continue;
      if (!from || !to || from === "?" || to === "?") throw new Error("Give both a month and a day for the from and to date of each range you use.");
      windows[season] = windows[season] || { season };
      windows[season][kind] = [from, to];
    }
    const sendDates = !this._editing || f._dates_changed;
    if (sendDates && Object.keys(windows).length) {
      data.windows = [...Object.values(windows), ...(this._extraWindows || [])];
    }
    else if (!data.based_on && !this._editing) throw new Error("Give at least one date range, or copy timing from a crop.");
    return data;
  }

  async _saveCrop() {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      await this._call("add_crop", this._cropPayload());
      await this._loadCrops();
      this._mode = "crops";
      this._form = {};
      this._editing = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  async _resetCrop(key) {
    this._busy = true;
    this._error = null;
    try {
      await this._call("reset_crop", { key });
      this._confirmDelete = null;
      await this._loadCrops();
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  async _deleteCrop(key) {
    this._busy = true;
    try {
      await this._call("remove_crop", { key });
      this._confirmDelete = null;
      await this._loadCrops();
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _cancel() {
    this._mode = { location: "locations", crop: "crops" }[this._mode] || null;
    this._form = {};
    this._preview = null;
    this._error = null;
    this._render();
  }

  // ----- rendering -----

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    root.append(h("style", {}, this._style()));

    const state = this._hass.states[this._config.entity];
    const card = h("ha-card", { header: this._config.title || this._defaultTitle() });
    const body = h("div", { class: "card-content" });
    card.append(body);
    root.append(card);

    if (!state) {
      body.append(h("p", { class: "muted" }, `Entity ${this._config.entity} not found. Is Reap set up?`));
      return;
    }
    if (this._error) {
      body.append(h("div", { class: "error" }, icon("mdi:alert-circle-outline"), this._error,
        this._cropsError && !this._crops
          ? h("button", { onclick: () => { this._cropsRetryAt = 0; this._loadCrops(); } }, "Retry")
          : null));
    }

    if (this._notice && !this._mode) {
      body.append(h("div", { class: "notice small" }, icon("mdi:information-outline"), h("span", {}, this._notice),
        h("button", { class: "icon-btn", title: "Dismiss", onclick: () => { this._notice = null; this._render(); } }, icon("mdi:close"))));
    }
    if (this._mode === "locations") {
      body.append(this._renderLocations());
      return;
    }
    if (this._mode === "location") {
      body.append(this._renderLocationForm());
      return;
    }
    if (this._mode === "crops") {
      body.append(this._renderCrops());
      return;
    }
    if (this._mode === "crop") {
      body.append(this._renderCropForm());
      return;
    }
    if (this._mode === "copy") {
      body.append(this._renderCopy());
      return;
    }
    if (this._mode) {
      body.append(this._renderForm());
      return;
    }
    this._renderHome(card, body);
  }

  _renderHome(card, body) {
    const plantings = this._plantings()
      .map((p) => ({ ...p, open: (p.tasks || []).filter((t) => !t.done_on) }))
      .filter((p) => this._config.show_done || p.open.length || p.open_count || p.problem)
      .sort((a, b) => ((a.open[0] || {}).due || "9999").localeCompare((b.open[0] || {}).due || "9999"));

    if (!plantings.length) {
      body.append(h("p", { class: "muted" }, "Nothing planned yet. Add your first planting."));
    }
    const list = h("div", { class: "list" });
    for (const p of plantings) list.append(this._renderRow(p));
    body.append(list);

    if (this._config.editable) {
      card.append(h("div", { class: "actions" },
        h("button", { onclick: () => this._openLocations() }, icon("mdi:map-marker-outline"), "Locations"),
        h("button", { onclick: () => this._openCrops(), disabled: !this._crops }, icon("mdi:sprout-outline"), "Crops"),
        this._config.planner_path
          ? h("button", { onclick: () => navigate(this._config.planner_path) }, icon("mdi:chart-timeline"), "Plan")
          : null,
        h("button", { class: "primary", onclick: () => this._startAdd(), disabled: !this._crops },
          icon("mdi:plus"), "Add planting")));
    }
  }

  _renderRow(p) {
    const crop = this._crop(p.crop);
    const next = p.open[0];
    const name = p.variety ? `${p.crop_name} (${p.variety})` : p.crop_name;
    const sowings = p.sowings || new Set((p.tasks || []).map((t) => t.succession)).size;
    const details = [
      METHOD_LABELS[p.method] || p.method,
      p.season && p.season !== "spring" ? p.season : null,
      String(p.year),
      sowings > 1 ? `${sowings} sowings, every ${p.succession_days} days` : null,
      p.location,
      p.quantity,
    ].filter(Boolean).join(" · ");

    const cfg = this._config;
    const size = Math.max(16, Number(cfg.icon_size) || 40);
    const lines = [h("div", { class: "name" }, name, " ", icon(METHOD_ICONS[p.method] || "mdi:sprout", "method"))];
    if (cfg.show_info && details) lines.push(h("div", { class: "muted small" }, details));
    if (p.problem) {
      // Can't be scheduled (after a settings change, say): say why.
      lines.push(h("div", { class: "error small" }, icon("mdi:alert-circle-outline"),
        `Needs attention: ${p.problem}`));
    } else if (cfg.show_next) {
      lines.push(next
        ? h("div", { class: "next small" }, icon(next.icon || "mdi:calendar"), `${shortDate(next.due)}: ${next.summary}`)
        : h("div", { class: "muted small" }, icon("mdi:check"), "All done"));
    }
    const iconBox = h("div", { class: "crop-icon" }, icon(p.icon || (crop && crop.icon) || "mdi:sprout"));
    iconBox.style.width = iconBox.style.height = `${size}px`;
    iconBox.style.setProperty("--mdc-icon-size", `${Math.round(size * 0.6)}px`);

    const row = h("div", { class: "row" },
      iconBox,
      h("div", { class: "info" }, lines),
      cfg.show_sensors ? this._renderSensors(this._location(p.location)) : null,
      cfg.editable
        ? h("div", { class: "row-actions" },
          h("button", { class: "icon-btn", title: "Edit", onclick: () => this._startEdit(p) }, icon("mdi:pencil")),
          h("button", { class: "icon-btn", title: "Remove", onclick: () => { this._confirmDelete = p.id; this._render(); } }, icon("mdi:delete-outline")))
        : null);

    if (this._confirmDelete === p.id) {
      return h("div", {}, row,
        h("div", { class: "confirm" },
          `Remove ${name}? Its open tasks come off your list.`,
          h("button", { onclick: () => { this._confirmDelete = null; this._render(); } }, "Keep"),
          h("button", { class: "danger", disabled: this._busy, onclick: () => this._delete(p.id) }, "Remove")));
    }
    return row;
  }

  _renderSensors(loc) {
    if (!loc || (!loc.soil_sensor && !loc.light)) return null;
    const box = h("div", { class: "sensors" });
    if (loc.soil_sensor) {
      const st = this._hass.states[loc.soil_sensor];
      const value = st ? parseFloat(st.state) : NaN;
      const ok = !Number.isNaN(value);
      box.append(h("button", {
        class: `chip moisture ${ok ? moistureLevel(value, this._config) : "unknown"}`,
        title: `${loc.name} soil moisture`,
        onclick: () => this._moreInfo(loc.soil_sensor),
      }, icon("mdi:water-percent"), ok ? `${Math.round(value)}%` : "--"));
    }
    if (loc.light) {
      const st = this._hass.states[loc.light];
      const on = st && st.state === "on";
      box.append(h("button", {
        class: `chip light ${on ? "on" : "off"}`,
        title: `${loc.name} light: ${st ? st.state : "unavailable"}`,
        onclick: () => this._moreInfo(loc.light),
      }, icon(on ? "mdi:lightbulb-on" : "mdi:lightbulb-outline")));
    }
    return box;
  }

  _renderLocations() {
    const wrap = h("div", { class: "form" });
    wrap.append(h("div", { class: "form-title" }, icon("mdi:map-marker-outline"), "Locations"));
    const list = h("div", { class: "list" });
    const locations = this._locations();
    if (!locations.length) list.append(h("p", { class: "muted" }, "No locations yet."));
    for (const loc of locations) {
      const used = loc.plantings || 0;
      const extras = [
        used ? `${used} planting${used === 1 ? "" : "s"}` : "Not used",
        loc.soil_sensor ? "soil sensor" : null,
        loc.light ? "light" : null,
      ].filter(Boolean).join(" · ");
      const row = h("div", { class: "row" },
        h("div", { class: "info" },
          h("div", { class: "name" }, loc.name),
          h("div", { class: "muted small" }, extras)),
        this._renderSensors(loc),
        h("div", { class: "row-actions" },
          h("button", { class: "icon-btn", title: "Edit", onclick: () => this._startLocation(loc) }, icon("mdi:pencil")),
          h("button", {
            class: "icon-btn", title: used ? "In use, so it can't be removed" : "Remove", disabled: used > 0,
            onclick: () => { this._confirmDelete = loc.id; this._render(); },
          }, icon("mdi:delete-outline"))));
      list.append(row);
      if (this._confirmDelete === loc.id) {
        list.append(h("div", { class: "confirm" },
          `Remove ${loc.name}?`,
          h("button", { onclick: () => { this._confirmDelete = null; this._render(); } }, "Keep"),
          h("button", { class: "danger", disabled: this._busy, onclick: () => this._deleteLocation(loc.id) }, "Remove")));
      }
    }
    wrap.append(list);
    wrap.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Done"),
      h("button", { class: "primary", onclick: () => this._startLocation(null) }, icon("mdi:plus"), "Add location")));
    return wrap;
  }

  _renderCrops() {
    const wrap = h("div", { class: "form" });
    wrap.append(h("div", { class: "form-title" }, icon("mdi:sprout-outline"), "Crops"));
    const all = this._crops || [];
    wrap.append(h("p", { class: "muted small" },
      "Your crop list. Edit any crop to match your garden, remove the ones you don't grow, or add your own. To add a variety, copy timing from the crop it's a variety of."));
    const list = h("div", { class: "list" });
    const filter = h("input", {
      type: "search", placeholder: `Search ${all.length} crops`, class: "search", value: this._cropFilter || "",
      oninput: (e) => {
        this._cropFilter = e.target.value;
        const q = e.target.value.trim().toLowerCase();
        for (const row of list.children) row.hidden = !!q && !(row.dataset.name || "").includes(q);
      },
    });
    wrap.append(filter);
    const q = (this._cropFilter || "").trim().toLowerCase();
    for (const crop of all) {
      const label = (CATEGORIES.find(([v]) => v === crop.category) || [null, "Vegetable"])[1];
      const tag = crop.custom ? "Your crop" : crop.edited ? "Edited" : null;
      const item = h("div", {},
        h("div", { class: "row" },
          h("div", { class: "crop-icon small-icon" }, icon(crop.icon || "mdi:sprout")),
          h("div", { class: "info" },
            h("div", { class: "name" }, crop.name),
            h("div", { class: "muted small" }, [label, tag, crop.in_use ? "in use" : null].filter(Boolean).join(" · "))),
          h("div", { class: "row-actions" },
            crop.edited
              ? h("button", { class: "icon-btn", title: "Undo my edits", disabled: this._busy, onclick: () => this._resetCrop(crop.key) }, icon("mdi:restore"))
              : null,
            h("button", { class: "icon-btn", title: "Edit", onclick: () => this._startCrop(crop) }, icon("mdi:pencil")),
            h("button", {
              class: "icon-btn", title: crop.in_use ? "In use, so it can't be removed" : "Remove", disabled: crop.in_use,
              onclick: () => { this._confirmDelete = crop.key; this._render(); },
            }, icon("mdi:delete-outline")))));
      item.dataset.name = crop.name.toLowerCase();
      item.hidden = !!q && !item.dataset.name.includes(q);
      if (this._confirmDelete === crop.key) {
        item.append(h("div", { class: "confirm" },
          crop.builtin ? `Remove ${crop.name}? You can bring it back later.` : `Remove ${crop.name}?`,
          h("button", { onclick: () => { this._confirmDelete = null; this._render(); } }, "Keep"),
          h("button", { class: "danger", disabled: this._busy, onclick: () => this._deleteCrop(crop.key) }, "Remove")));
      }
      list.append(item);
    }
    wrap.append(list);
    const hidden = this._hiddenCrops || [];
    if (hidden.length) {
      const removed = h("details", { class: "removed" },
        h("summary", {}, `Removed crops (${hidden.length})`));
      for (const crop of hidden) {
        removed.append(h("div", { class: "row" },
          h("div", { class: "crop-icon small-icon" }, icon(crop.icon || "mdi:sprout")),
          h("div", { class: "info" }, h("div", { class: "name muted" }, crop.name)),
          h("button", { disabled: this._busy, onclick: () => this._resetCrop(crop.key) }, icon("mdi:restore"), "Restore")));
      }
      wrap.append(removed);
    }
    wrap.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Done"),
      h("button", { class: "primary", onclick: () => this._startCrop(null) }, icon("mdi:plus"), "Add crop")));
    return wrap;
  }

  // A month and day picker; the value is "MM-DD" (no year, it repeats yearly).
  _monthDay(key, label) {
    const [mm, dd] = (this._form[key] || "").split("-");
    const month = h("select", {}, h("option", { value: "" }, "--"),
      MONTHS.map((name, i) => {
        const v = String(i + 1).padStart(2, "0");
        return h("option", { value: v, selected: v === mm }, name);
      }));
    const day = h("select", {}, h("option", { value: "" }, "--"),
      Array.from({ length: 31 }, (_, i) => {
        const v = String(i + 1).padStart(2, "0");
        return h("option", { value: v, selected: v === dd }, String(i + 1));
      }));
    const update = () => {
      this._form[key] = month.value && day.value ? `${month.value}-${day.value}` : (month.value || day.value ? "?" : "");
      this._form._dates_changed = true;
    };
    month.addEventListener("change", () => { if (month.value && !day.value) day.value = "01"; update(); });
    day.addEventListener("change", update);
    return h("label", { class: "field" }, h("span", {}, label), h("div", { class: "md" }, month, day));
  }

  _check(key, label) {
    return h("label", { class: "check" },
      h("input", { type: "checkbox", checked: !!this._form[key], onchange: (e) => { this._form[key] = e.target.checked; } }),
      label);
  }

  _renderCropForm() {
    const f = this._form;
    const form = h("div", { class: "form" });
    const preview = icon(f.icon || "mdi:sprout");
    form.append(h("div", { class: "form-title" }, preview,
      this._editing ? `Edit ${f.name || "crop"}` : "Add a crop"));
    form.append(h("div", { class: "grid" },
      this._input("name", "Name", "text", { placeholder: "Tomato, Sungold" }),
      this._select("category", "Category", CATEGORIES)));
    const iconField = this._input("icon", "Icon (optional)", "text", { placeholder: "mdi:chili-mild" });
    iconField.querySelector("input").addEventListener("input", (e) => { preview.icon = e.target.value || "mdi:sprout"; });
    form.append(iconField);
    if (!this._editing) {
      const others = (this._crops || []).map((c) => [c.key, c.name]);
      form.append(this._select("based_on", "Copy timing from (optional)", [["", "Nothing, I'll enter dates"], ...others],
        (value) => {
          f.based_on = value;
          const base = this._crop(value);
          if (base && !f.icon) f.icon = base.icon;
          if (base && !f.category) f.category = base.category;
          if (base) {
            // A copy keeps how the crop is grown and timed.
            f.planted = !!base.planted;
            f.frost_tender = !!base.frost_tender;
            f.perennial = !!base.perennial;
          }
          this._render();
        }));
    }
    form.append(h("p", { class: "muted small" }, f.based_on
      ? "Dates are optional. Leave them empty to use the copied crop's timing."
      : this._editing
      ? "These are the dates for your garden. Change any of them, and the rest of the crop stays as it is."
      : "Enter the dates you'd usually do each step in your garden, using the ones that apply. They repeat every year."));
    const range = (field, label) => h("div", { class: "range" },
      h("span", { class: "range-label" }, label),
      this._monthDay(`${field}_from`, "From"),
      this._monthDay(`${field}_to`, "To"));
    form.append(range("spring_indoor", "Start indoors"));
    form.append(range("spring_transplant", "Transplant out"));
    form.append(range("spring_direct", "Direct sow (spring)"));
    // Summer and fall plantings, folded away unless the crop has them.
    for (const [season, title] of [["summer", "Summer planting"], ["fall", "Fall planting"]]) {
      const used = ["indoor", "transplant", "direct"].some((k) => f[`${season}_${k}_from`] || f[`${season}_${k}_to`]);
      const details = h("details", { class: "season", open: used || season === "fall" },
        h("summary", {}, title),
        range(`${season}_indoor`, "Start indoors"),
        range(`${season}_transplant`, "Transplant out"),
        range(`${season}_direct`, season === "fall" ? "Direct sow or plant" : "Direct sow"));
      details.addEventListener("toggle", () => { this._open = this._open || {}; this._open[season] = details.open; });
      if (this._open && season in this._open) details.open = this._open[season];
      form.append(details);
    }
    form.append(h("div", { class: "grid" },
      this._input("days_to_harvest", "Days to harvest", "number", { min: 1, max: 1100, placeholder: "60" }),
      this._input("harvest_weeks", "Harvest lasts (weeks)", "number", { min: 1, max: 52, placeholder: "4" }),
      this._input("weeks_indoor", "Weeks indoors (optional)", "number", { min: 1, max: 30 })));
    form.append(this._check("frost_tender", "Frost tender (timed from the warm-crop frost date)"));
    form.append(this._check("planted", "Planted from cloves, sets, tubers or slips (tasks say Plant, not Sow)"));
    form.append(this._check("perennial", "Perennial"));
    form.append(this._input("notes", "Notes"));
    form.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Cancel"),
      h("button", { class: "primary", disabled: this._busy, onclick: () => this._saveCrop() },
        icon("mdi:content-save-outline"), this._editing ? "Save" : "Add")));
    return form;
  }

  // Home Assistant's own searchable entity picker, loaded on demand. Until
  // it's available, a text box that suggests matching entities as you type.
  async _ensurePickers() {
    if (customElements.get("ha-entity-picker") || this._loadingPickers || !window.loadCardHelpers) return;
    this._loadingPickers = true;
    try {
      const helpers = await window.loadCardHelpers();
      const card = await helpers.createCardElement({ type: "entities", entities: [] });
      if (card && card.constructor.getConfigElement) await card.constructor.getConfigElement();
      await Promise.race([customElements.whenDefined("ha-entity-picker"), new Promise((r) => setTimeout(r, 3000))]);
    } catch (err) {
      // The text box stays.
    }
    this._loadingPickers = false;
    if (this._mode === "location" && customElements.get("ha-entity-picker")) this._render();
  }

  _entityField(key, label, domains, preferred) {
    if (customElements.get("ha-entity-picker")) {
      const picker = document.createElement("ha-entity-picker");
      picker.hass = this._hass;
      picker.label = label;
      picker.value = this._form[key] || "";
      picker.includeDomains = domains;
      picker.addEventListener("value-changed", (e) => { this._form[key] = e.detail.value || ""; });
      return h("div", { class: "field picker" }, picker);
    }
    const listId = `reap-${key}-options`;
    const ids = Object.keys(this._hass.states)
      .filter((id) => domains.includes(id.split(".")[0]))
      .sort((a, b) => {
        // Matching entities first, then in the order the domains are listed.
        const rank = (id) => (preferred && preferred(id, this._hass.states[id]) ? 0 : 100)
          + domains.indexOf(id.split(".")[0]);
        return rank(a) - rank(b) || a.localeCompare(b);
      });
    return h("label", { class: "field" }, h("span", {}, label),
      h("input", {
        type: "search", list: listId, value: this._form[key] || "", placeholder: "Type to search, or leave empty",
        autocomplete: "off", oninput: (e) => { this._form[key] = e.target.value.trim(); },
      }),
      h("datalist", { id: listId }, ids.map((id) => {
        const name = this._hass.states[id].attributes.friendly_name;
        return h("option", { value: id }, name ? `${name}` : id);
      })));
  }

  _renderLocationForm() {
    const form = h("div", { class: "form" });
    form.append(h("div", { class: "form-title" }, icon("mdi:map-marker-outline"),
      this._editing ? `Edit ${this._form.name || "location"}` : "Add a location"));
    form.append(this._input("name", "Name", "text", { placeholder: "Bed 3" }));
    const soil = (id, st) => id.startsWith("sensor.") && (
      st.attributes.device_class === "moisture" ||
      (st.attributes.unit_of_measurement === "%" && /soil|moist/i.test(`${id} ${st.attributes.friendly_name || ""}`)));
    // Soil sensors first: ones that look like moisture sensors, but any
    // sensor can be picked by searching.
    form.append(this._entityField("soil_sensor", "Soil moisture sensor (optional)", ["sensor"], soil));
    form.append(this._entityField("light", "Light (optional)", ["light", "switch", "input_boolean"]));
    form.append(this._entityField("water", "Watering valve or switch (optional)", ["valve", "switch", "input_boolean"]));
    form.append(this._entityField("camera", "Camera (optional)", ["camera"]));
    form.append(h("p", { class: "muted small" },
      "Renaming a location moves its plantings with it."));
    form.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Cancel"),
      h("button", { class: "primary", disabled: this._busy, onclick: () => this._saveLocation() },
        icon("mdi:content-save-outline"), this._editing ? "Save" : "Add")));
    return form;
  }

  _input(key, label, type = "text", extra = {}) {
    const value = this._form[key] === undefined || this._form[key] === null ? "" : this._form[key];
    return h("label", { class: "field" }, h("span", {}, label),
      h("input", {
        type, value, ...extra,
        oninput: (e) => {
          this._form[key] = e.target.value;
          this._preview = null;
          if (/_(from|to)$/.test(key)) this._form._dates_changed = true;
        },
      }));
  }

  _select(key, label, options, onchange) {
    const select = h("select", {
      onchange: (e) => {
        if (onchange) onchange(e.target.value);
        else { this._form[key] = e.target.value; this._preview = null; }
      },
    }, options.map(([value, text]) => h("option", { value, selected: this._form[key] === value }, text)));
    return h("label", { class: "field" }, h("span", {}, label), select);
  }

  _locationSelect() {
    const names = this._locations().map((l) => l.name);
    const current = this._form.location;
    if (current && !names.some((n) => n.toLowerCase() === current.toLowerCase())) names.push(current);
    return this._select("location", "Location", [["", "None"], ...names.map((n) => [n, n])]);
  }

  _renderForm() {
    const crop = this._crop(this._form.crop);
    const form = h("div", { class: "form" });
    const adding = this._mode === "add";
    const bulk = adding && this._form.bulk;
    form.append(h("div", { class: "form-title" },
      icon(bulk ? "mdi:sprout-outline" : (crop && crop.icon) || "mdi:sprout"),
      adding ? (bulk ? "Add several crops" : "Add a planting") : `Edit ${crop ? crop.name : this._form.crop}`));
    if (adding) {
      const tab = (value, label) => h("button", {
        class: `tab${!!this._form.bulk === value ? " active" : ""}`,
        onclick: () => {
          // Several crops start from each crop's own defaults, not the one picked above.
          if (value && !this._form.bulk) {
            this._form.single_location = this._form.location;
            this._form.location = "";
          } else if (!value && this._form.bulk) {
            this._form.location = this._form.single_location || "";
          }
          this._form.bulk = value; this._preview = null; this._error = null; this._render();
        },
      }, label);
      form.append(h("div", { class: "tabs" }, tab(false, "One crop"), tab(true, "Several crops")));
      if (bulk) return this._renderBulk(form);
    }

    const crops = (this._crops || []).map((c) => [c.key, c.name]);
    form.append(this._select("crop", "Crop", crops, (key) => this._pickCrop(key)));
    if (crop) {
      form.append(this._select("method", "Method", crop.methods.map((m) => [m, METHOD_LABELS[m] || m])));
      if (crop.seasons.length > 1) {
        form.append(this._select("season", "Season", crop.seasons.map((s) => [s, s[0].toUpperCase() + s.slice(1)])));
      }
      if (crop.notes) form.append(h("p", { class: "muted small" }, icon("mdi:information-outline"), crop.notes));
    }
    form.append(h("div", { class: "grid" },
      this._input("year", "Year", "number", { min: 2000, max: 2100, placeholder: "Next season" }),
      this._input("start_date", "Start date (optional)", "date"),
      this._input("succession_days", "Repeat every (days)", "number", { min: 0, max: 365 }),
      this._input("succession_count", "Number of sowings", "number", { min: 1, max: 200 }),
      this._input("succession_until", "Repeat until", "date"),
      adding ? null : this._input("variety", "Variety"),
      adding ? null : this._input("quantity", "Quantity", "text", { placeholder: "6 cells" }),
      this._locationSelect()));
    if (adding) form.append(this._renderVarieties());
    form.append(this._input("notes", "Notes"));
    form.append(h("label", { class: "check" },
      h("input", {
        type: "checkbox", checked: !!this._form.save_defaults,
        onchange: (e) => { this._form.save_defaults = e.target.checked; },
      }),
      "Save method, repeat, sowings, quantity and location as the default for this crop"));
    form.append(h("p", { class: "muted small" },
      "Start date is the transplant date for indoor starts, or the first sowing for direct sowing. Leave it empty to use the crop's usual window."
      + (adding && this._form.varieties.length > 1 ? " Preview shows the first variety; the others get the same dates." : "")));

    if (this._preview) {
      const list = h("div", { class: "preview" });
      for (const t of this._preview.slice(0, 30)) {
        list.append(h("div", { class: "small" }, icon(t.icon || "mdi:calendar"), `${shortDate(t.due, true)}: ${t.summary}`));
      }
      if (this._preview.length > 30) list.append(h("div", { class: "muted small" }, `...and ${this._preview.length - 30} more`));
      form.append(list);
    }

    form.append(h("div", { class: "actions" },
      h("button", { onclick: () => this._cancel() }, "Cancel"),
      h("button", { disabled: this._busy || !crop, onclick: () => this._doPreview() }, icon("mdi:calendar-search"), "Preview dates"),
      h("button", { class: "primary", disabled: this._busy || !crop, onclick: () => this._save() },
        icon("mdi:content-save-outline"),
        adding && this._form.varieties.filter((r) => r.variety.trim()).length > 1
          ? `Add ${this._form.varieties.filter((r) => r.variety.trim()).length} plantings`
          : adding ? "Add" : "Save")));
    return form;
  }
}

// ----- the planner card: one growing year as a season chart -----

const PLANNER_DEFAULTS = {
  entity: "sensor.reap_plantings",
  group_by: "date",
  max_height: 480,
  editable: true,
  show_sensors: false,
};
// Calendar month (0 = January) to season, northern hemisphere.
const NORTH_SEASONS = ["winter", "winter", "spring", "spring", "spring", "summer",
  "summer", "summer", "fall", "fall", "fall", "winter"];
const SEASON_NAMES = { winter: "Winter", spring: "Spring", summer: "Summer", fall: "Fall" };
const PHASES = ["indoor", "out", "sow", "harvest"];

// Whole days since 1970, so date maths ignores time zones and clock changes.
function dayNum(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function monthName(month, style) {
  try {
    return new Date(2001, month, 1).toLocaleDateString(LOCALE, { month: style });
  } catch (err) {
    return new Date(2001, month, 1).toLocaleDateString(undefined, { month: style });
  }
}

class ReapPlannerCard extends ReapCard {
  setConfig(config) {
    this._group = (config && config.group_by) || PLANNER_DEFAULTS.group_by;
    this._selected = null;
    super.setConfig({ ...PLANNER_DEFAULTS, ...config });
  }

  static getConfigElement() {
    return document.createElement("reap-planner-card-editor");
  }

  static getStubConfig() {
    return { entity: "sensor.reap_plantings" };
  }

  getCardSize() {
    return 8;
  }

  // A twelve-month chart needs the full width of a Sections view.
  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  _style() {
    return STYLE + PLANNER_STYLE;
  }

  // Redrawing rebuilds the chart, so keep its scroll position, and bring a
  // planting's details into view when it's opened.
  _render() {
    const old = this.shadowRoot && this.shadowRoot.querySelector(".chart");
    const top = old ? old.scrollTop : 0;
    super._render();
    const chart = this.shadowRoot && this.shadowRoot.querySelector(".chart");
    if (!chart) return;
    chart.scrollTop = top;
    if (this._reveal) {
      this._reveal = false;
      const detail = chart.querySelector(".plan-detail");
      const row = detail && detail.previousElementSibling;
      if (detail) {
        const head = chart.querySelector(".chart-head");
        const view = chart.getBoundingClientRect();
        const topEdge = view.top + (head ? head.offsetHeight : 0);
        const a = row.getBoundingClientRect();
        const b = detail.getBoundingClientRect();
        if (b.bottom > view.bottom) chart.scrollTop += Math.min(b.bottom - view.bottom, a.top - topEdge);
        else if (a.top < topEdge) chart.scrollTop -= topEdge - a.top;
      }
    }
  }

  _defaultTitle() {
    return "Garden plan";
  }

  _copied(year) {
    this._view = year;
    this._selected = null;
  }

  _southern() {
    const state = this._hass && this._hass.states[this._config.entity];
    return !!(state && state.attributes.southern);
  }

  // A southern growing year runs July to June and is named for the year its
  // spring is in.
  _growingYear(iso) {
    const [y, m] = iso.split("-").map(Number);
    return this._southern() && m < 7 ? y - 1 : y;
  }

  _range(year) {
    return this._southern()
      ? [dayNum(`${year}-07-01`), dayNum(`${year + 1}-07-01`)]
      : [dayNum(`${year}-01-01`), dayNum(`${year + 1}-01-01`)];
  }

  _yearLabel(year) {
    return this._southern() ? `${year}–${String(year + 1).slice(2)}` : String(year);
  }

  _yearBounds() {
    const now = this._growingYear(todayIso());
    const years = this._plantings().map((p) => p.year);
    return [Math.min(now, ...years), Math.max(now, ...years) + 1];
  }

  // This growing year, or the first later one with sowing still ahead.
  _defaultYear() {
    const today = todayIso();
    const now = this._growingYear(today);
    const busy = this._plantings()
      .filter((p) => p.year >= now && p.timeline &&
        ["indoor", "out", "sow"].some((k) => p.timeline[k] && !p.timeline[k].done && p.timeline[k].end >= today))
      .map((p) => p.year);
    return busy.length ? Math.min(...busy) : now;
  }

  _name(p) {
    return p.variety ? `${p.crop_name} (${p.variety})` : p.crop_name;
  }

  // The plantings drawn for a year: its own, plus other years' plantings
  // still growing in it (fall garlic in the spring after, say).
  _rows(year) {
    const [r0, r1] = this._range(year);
    const rows = [];
    for (const p of this._plantings()) {
      const phases = PHASES.map((k) => p.timeline && p.timeline[k]).filter(Boolean);
      const overlaps = phases.some((ph) => dayNum(ph.end) >= r0 && dayNum(ph.start) < r1);
      if (p.year !== year && !overlaps) continue;
      const first = phases.length ? Math.max(Math.min(...phases.map((ph) => dayNum(ph.start))), r0 - 1) : r1;
      rows.push({ p, other: p.year !== year, first });
    }
    rows.sort((a, b) => (a.other === b.other ? 0 : a.other ? -1 : 1) || a.first - b.first ||
      this._name(a.p).localeCompare(this._name(b.p)));
    return rows;
  }

  _groups(rows) {
    if (this._group === "crop") {
      const sorted = [...rows].sort((a, b) => this._name(a.p).localeCompare(this._name(b.p), LOCALE) ||
        (a.other === b.other ? 0 : a.other ? -1 : 1) || a.first - b.first);
      return [{ name: null, rows: sorted }];
    }
    if (this._group !== "location") return [{ name: null, rows }];
    const order = this._locations().map((l) => l.name.toLowerCase());
    const groups = new Map();
    for (const row of rows) {
      const name = row.p.location || "";
      const key = name.toLowerCase();
      if (!groups.has(key)) groups.set(key, { name: name || "No location", key, rows: [] });
      groups.get(key).rows.push(row);
    }
    const rank = (key) => (key === "" ? 1e6 : order.indexOf(key) === -1 ? 1e5 : order.indexOf(key));
    return [...groups.values()].sort((a, b) => rank(a.key) - rank(b.key) || a.name.localeCompare(b.name));
  }

  // Month columns of the chart: [calendar month, first day, days].
  _months(year) {
    const start = this._southern() ? 6 : 0;
    const months = [];
    for (let i = 0; i < 12; i++) {
      const month = (start + i) % 12;
      const y = year + (start + i >= 12 ? 1 : 0);
      const first = dayNum(`${y}-${String(month + 1).padStart(2, "0")}-01`);
      const next = month === 11 ? dayNum(`${y + 1}-01-01`) : dayNum(`${y}-${String(month + 2).padStart(2, "0")}-01`);
      months.push([month, first, next - first]);
    }
    return months;
  }

  _season(month) {
    return NORTH_SEASONS[this._southern() ? (month + 6) % 12 : month];
  }

  _renderHome(card, body) {
    const bounds = this._yearBounds();
    if (this._view === undefined || this._view === null) this._view = this._defaultYear();
    const year = Math.min(Math.max(this._view, bounds[0]), bounds[1]);
    this._view = year;
    const [r0, r1] = this._range(year);
    const total = r1 - r0;
    const pct = (day) => `${((day - r0) / total) * 100}%`;
    const months = this._months(year);
    const today = dayNum(todayIso());

    // Season tints behind every row, one stop per month.
    const stops = months.map(([month, first, days]) =>
      `var(--reap-${this._season(month)}) ${pct(first)} ${pct(first + days)}`);
    const tint = `linear-gradient(90deg, ${stops.join(", ")})`;

    const rows = this._rows(year);
    const own = rows.filter((r) => !r.other).map((r) => r.p);
    const places = new Set(own.map((p) => (p.location || "").toLowerCase()).filter(Boolean));
    const problems = own.filter((p) => p.problem).length;

    const nav = (delta, label, iconName) => h("button", {
      class: "icon-btn", title: label, "aria-label": label,
      disabled: year + delta < bounds[0] || year + delta > bounds[1],
      onclick: () => { this._view = year + delta; this._selected = null; this._confirmDelete = null; this._render(); },
    }, icon(iconName));
    const tab = (key, label) => h("button", {
      class: `seg${this._group === key ? " on" : ""}`, "aria-pressed": this._group === key ? "true" : "false",
      onclick: () => { this._group = key; this._render(); },
    }, label);
    body.append(h("div", { class: "plan-bar" },
      h("div", { class: "year" }, nav(-1, "Previous year", "mdi:chevron-left"),
        h("span", { class: "year-label" }, this._yearLabel(year)),
        nav(1, "Next year", "mdi:chevron-right")),
      h("div", { class: "segs" }, tab("date", "By date"), tab("crop", "By crop"), tab("location", "By location"))));
    body.append(h("div", { class: "muted small plan-summary" }, [
      `${own.length} planting${own.length === 1 ? "" : "s"}`,
      places.size ? `${places.size} location${places.size === 1 ? "" : "s"}` : null,
      problems ? `${problems} need${problems === 1 ? "s" : ""} attention` : null,
    ].filter(Boolean).join(" · ")));

    if (!own.length) {
      const before = this._plantings().some((p) => p.year === year - 1);
      body.append(h("div", { class: "plan-empty" },
        icon("mdi:calendar-blank-outline"),
        h("div", { class: "name" }, `Nothing planned for ${this._yearLabel(year)} yet`),
        h("div", { class: "muted small" }, before
          ? "Start from last season's plan, or add plantings."
          : "Add plantings to see them here."),
        this._config.editable ? h("div", { class: "row-actions gap" },
          h("button", { onclick: () => this._startAdd(), disabled: !this._crops }, icon("mdi:plus"), "Add planting"),
          before ? h("button", { class: "primary", onclick: () => this._startCopy(year - 1, year) },
            icon("mdi:content-copy"), `Copy ${this._yearLabel(year - 1)} here`) : null) : null));
      if (!rows.length) {
        this._renderLegend(body);
        return;
      }
    }

    const chart = h("div", { class: "chart" });
    const maxHeight = Number(this._config.max_height) || 0;
    if (maxHeight > 0) chart.style.maxHeight = `${maxHeight}px`;

    // Season names over the months they cover, then the months.
    const seasons = [];
    for (const [month, first, days] of months) {
      const name = this._season(month);
      const last = seasons[seasons.length - 1];
      if (last && last.name === name) last.days += days;
      else seasons.push({ name, first, days });
    }
    const seasonRow = h("div", { class: "track head" }, seasons.map((s) => {
      const el = h("div", { class: `season-name ${s.name}${s.days < 45 ? " part" : ""}` }, SEASON_NAMES[s.name]);
      el.style.left = pct(s.first);
      el.style.width = `${(s.days / total) * 100}%`;
      return el;
    }));
    const monthRow = h("div", { class: "track head" }, months.map(([month, first, days]) => {
      const el = h("div", { class: "month" },
        h("span", { class: "long" }, monthName(month, "short")),
        h("span", { class: "short" }, monthName(month, "narrow")));
      el.style.left = pct(first);
      el.style.width = `${(days / total) * 100}%`;
      return el;
    }));
    chart.append(h("div", { class: "chart-head" },
      h("div", { class: "prow head" }, h("div", { class: "plabel" }), seasonRow),
      h("div", { class: "prow head" }, h("div", { class: "plabel" }), monthRow)));

    for (const group of this._groups(rows)) {
      if (group.name) chart.append(h("div", { class: "group-name" }, group.name));
      for (const row of group.rows) {
        chart.append(this._renderPlanRow(row, year, { r0, r1, pct, tint, today }));
        if (this._selected === row.p.id) chart.append(this._renderPlanDetail(row, year));
      }
    }
    body.append(chart);
    this._renderLegend(body);

    if (this._config.editable && own.length) {
      card.append(h("div", { class: "actions" },
        h("button", { onclick: () => this._startAdd(), disabled: !this._crops }, icon("mdi:plus"), "Add planting"),
        own.length
          ? h("button", { class: "primary", onclick: () => this._startCopy(year, year + 1) },
            icon("mdi:content-copy"), `Copy to ${this._yearLabel(year + 1)}`)
          : null));
    }
  }

  _renderPlanRow(row, year, { r0, r1, pct, tint, today }) {
    const p = row.p;
    const t = p.timeline || {};
    const track = h("div", { class: "track" });
    track.style.background = tint;
    const span = (kind, ph) => {
      const s = Math.max(dayNum(ph.start), r0);
      const e = Math.min(dayNum(ph.end) + 1, r1);
      if (e <= s) return;
      const el = h("div", { class: `bar ${kind}${ph.done ? " done" : ""}` });
      el.style.left = pct(s);
      el.style.width = `max(${((e - s) / (r1 - r0)) * 100}%, 6px)`;
      track.append(el);
    };
    if (t.grow) span("grow", t.grow);
    // Seedlings are indoors from sowing until they're planted out.
    if (t.indoor) span("indoor", t.out && t.out.start > t.indoor.end ? { ...t.indoor, end: t.out.start } : t.indoor);
    if (t.sow) span("sow", t.sow);
    if (t.harvest) span("harvest", t.harvest);
    if (t.out) {
      for (const day of new Set([t.out.start, t.out.end])) {
        const d = dayNum(day);
        if (d < r0 || d >= r1) continue;
        const dot = h("div", { class: `dot${t.out.done ? " done" : ""}` });
        dot.style.left = pct(d + 0.5);
        track.append(dot);
      }
    }
    // Repeated sowings can run on into the harvest: draw them one above the other.
    if (t.sow && t.harvest && t.harvest.start <= t.sow.end) track.classList.add("stack");
    const ends = PHASES.map((k) => t[k]).filter(Boolean);
    if (ends.some((ph) => dayNum(ph.end) >= r1)) track.append(h("div", { class: "more after" }, icon("mdi:chevron-right")));
    if (ends.some((ph) => dayNum(ph.start) < r0)) track.append(h("div", { class: "more before" }, icon("mdi:chevron-left")));
    if (today >= r0 && today < r1) {
      const line = h("div", { class: "today" });
      line.style.left = pct(today + 0.5);
      track.append(line);
    }

    const sub = row.other
      ? [`From ${this._yearLabel(p.year)}`, p.location]
      : [p.location || null, p.problem ? null : (METHOD_LABELS[p.method] || p.method)];
    const selected = this._selected === p.id;
    const label = h("div", { class: "plabel" },
      h("div", { class: "pname" }, icon(p.icon || "mdi:sprout"), h("span", {}, this._name(p))),
      p.problem
        ? h("div", { class: "error small" }, icon("mdi:alert-circle-outline"), "Needs attention")
        : h("div", { class: "muted psub" }, sub.filter(Boolean).join(" · ")));
    return h("button", {
      class: `prow${row.other ? " other" : ""}${selected ? " selected" : ""}`,
      title: [this._name(p), ...sub].filter(Boolean).join(" \u00b7 "),
      "aria-expanded": selected ? "true" : "false",
      onclick: () => {
        this._selected = selected ? null : p.id;
        this._reveal = !selected;
        this._confirmDelete = null;
        this._render();
      },
    }, label, track);
  }

  _renderPlanDetail(row, year) {
    const p = row.p;
    const t = p.timeline || {};
    const crop = this._crop(p.crop);
    const when = (ph) => {
      const withYear = (iso) => this._growingYear(iso) !== year;
      const a = shortDate(ph.start, withYear(ph.start));
      const b = shortDate(ph.end, withYear(ph.end));
      return a === b ? a : `${a} – ${b}`;
    };
    const labels = {
      indoor: "Start indoors",
      out: "Plant out",
      sow: crop && crop.planted ? "Plant outside" : "Sow outside",
      harvest: "Harvest",
    };
    const steps = h("div", { class: "steps" });
    for (const kind of PHASES) {
      if (!t[kind]) continue;
      steps.append(h("div", { class: "step" },
        h("span", { class: `swatch ${kind}` }),
        h("span", { class: "muted step-label" }, labels[kind]),
        h("span", {}, when(t[kind])),
        t[kind].done ? icon("mdi:check", "done-mark") : null));
    }
    const sowings = p.sowings || 0;
    const facts = [
      row.other ? `From the ${this._yearLabel(p.year)} plan` : null,
      METHOD_LABELS[p.method] || p.method,
      p.season && p.season !== "spring" ? `${p.season} planting` : null,
      sowings > 1 ? `${sowings} sowings, every ${p.succession_days} days` : null,
      p.location,
      p.quantity,
    ].filter(Boolean).join(" · ");
    const box = h("div", { class: "plan-detail" },
      h("div", { class: "muted small" }, facts),
      p.problem ? h("div", { class: "error small" }, icon("mdi:alert-circle-outline"), p.problem) : null,
      steps.childElementCount ? steps : null,
      p.notes ? h("div", { class: "muted small" }, p.notes) : null);
    if (this._config.editable) {
      if (this._confirmDelete === p.id) {
        box.append(h("div", { class: "confirm" },
          `Remove ${this._name(p)}? Its open tasks come off your list.`,
          h("button", { onclick: () => { this._confirmDelete = null; this._render(); } }, "Keep"),
          h("button", { class: "danger", disabled: this._busy, onclick: () => this._delete(p.id) }, "Remove")));
      } else {
        box.append(h("div", { class: "row-actions gap" },
          h("button", { onclick: () => this._startEdit(p), disabled: !this._crops }, icon("mdi:pencil"), "Edit"),
          h("button", { onclick: () => { this._confirmDelete = p.id; this._render(); } }, icon("mdi:delete-outline"), "Remove")));
      }
    }
    return box;
  }

  _renderLegend(body) {
    const item = (cls, text) => h("span", { class: "legend-item" }, h("span", { class: `swatch ${cls}` }), text);
    body.append(h("div", { class: "legend muted" },
      item("indoor", "Start indoors"), item("sow", "Sow outside"), item("out", "Plant out"),
      item("grow", "Growing"), item("harvest", "Harvest")));
  }
}

const PLANNER_STYLE = `
  :host {
    --reap-indoor: var(--reap-indoor-color, var(--purple-color, #926bc7));
    --reap-sow: var(--reap-sow-color, var(--green-color, #4caf50));
    --reap-harvest: var(--reap-harvest-color, var(--amber-color, #ffc107));
    --reap-grow: var(--reap-grow-color, var(--secondary-text-color));
    --reap-winter: var(--reap-winter-color, color-mix(in srgb, var(--blue-color, #2196f3) 11%, transparent));
    --reap-spring: var(--reap-spring-color, color-mix(in srgb, var(--green-color, #4caf50) 11%, transparent));
    --reap-summer: var(--reap-summer-color, color-mix(in srgb, var(--amber-color, #ffc107) 14%, transparent));
    --reap-fall: var(--reap-fall-color, color-mix(in srgb, var(--deep-orange-color, #ff6f22) 11%, transparent));
    --reap-card-bg: var(--ha-card-background, var(--card-background-color, #fff));
  }
  .plan-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
  .year { display: flex; align-items: center; }
  .year-label { font-size: 1.1em; font-weight: 500; min-width: 64px; text-align: center; }
  .segs { display: flex; border: 1px solid var(--divider-color); border-radius: 18px; overflow: hidden; }
  button.seg { border: none; border-radius: 0; padding: 6px 12px; font-size: 0.875em; background: none; color: var(--secondary-text-color); }
  button.seg.on { background: color-mix(in srgb, var(--primary-color) 16%, transparent); color: var(--primary-text-color); }
  .plan-summary { padding: 2px 0 8px; }
  .chart { overflow-y: auto; container-type: inline-size; margin: 0 -16px; }
  .chart-head { position: sticky; top: 0; z-index: 2; background: var(--reap-card-bg); border-bottom: 1px solid var(--divider-color);
    -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px); }
  button.prow, .prow { display: flex; align-items: center; width: 100%; box-sizing: border-box; gap: 0; padding: 4px 16px;
    margin: 0; border: none; border-radius: 0; background: none; color: inherit; text-align: left; font: inherit; }
  button.prow { cursor: pointer; }
  button.prow:hover { background: var(--secondary-background-color); }
  button.prow.selected { background: color-mix(in srgb, var(--primary-color) 13%, transparent); }
  button.prow.other .plabel, button.prow.other .track > div { opacity: 0.5; }
  .prow.head { padding-top: 0; padding-bottom: 0; }
  .plabel { width: 170px; flex: none; min-width: 0; padding-right: 10px; box-sizing: border-box; }
  .pname { display: flex; align-items: center; gap: 6px; font-weight: 500; font-size: 0.95em; }
  .pname span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pname ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); flex: none; }
  .psub { font-size: 0.8em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-left: 24px; }
  .plabel .error { padding: 0 0 0 24px; font-size: 0.8em; }
  .track { position: relative; flex: 1; height: 30px; border-radius: 6px; }
  .track.head { height: 22px; border-radius: 0; }
  .season-name { position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center; overflow: hidden;
    font-size: 0.7em; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap; }
  .season-name.winter { color: color-mix(in srgb, var(--blue-color, #2196f3) 65%, var(--primary-text-color)); }
  .season-name.spring { color: color-mix(in srgb, var(--green-color, #4caf50) 65%, var(--primary-text-color)); }
  .season-name.summer { color: color-mix(in srgb, var(--amber-color, #ffc107) 60%, var(--primary-text-color)); }
  .season-name.fall { color: color-mix(in srgb, var(--deep-orange-color, #ff6f22) 65%, var(--primary-text-color)); }
  .month { position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center;
    font-size: 0.75em; color: var(--secondary-text-color); }
  .month .short { display: none; }
  .bar { position: absolute; top: 50%; transform: translateY(-50%); height: 12px; border-radius: 6px; box-sizing: border-box; }
  .bar.grow { height: 2px; border-radius: 1px; background: var(--reap-grow); opacity: 0.7; }
  .bar.indoor, .swatch.indoor { border: 1px solid var(--reap-indoor);
    background: repeating-linear-gradient(135deg, var(--reap-indoor) 0 2px, color-mix(in srgb, var(--reap-indoor) 30%, transparent) 2px 5px); }
  .bar.sow, .swatch.sow { background: var(--reap-sow); }
  .bar.harvest, .swatch.harvest { background: var(--reap-harvest); border: 1px solid color-mix(in srgb, var(--reap-harvest) 70%, var(--primary-text-color)); }
  .bar.done { filter: saturate(0.45); opacity: 0.45; }
  .track.stack .bar.sow { top: 32%; height: 9px; }
  .track.stack .bar.harvest { top: 68%; height: 9px; }
  .dot, .swatch.out { width: 12px; height: 12px; border-radius: 50%; box-sizing: border-box; background: var(--reap-card-bg); border: 2.5px solid var(--reap-sow); }
  .dot { position: absolute; top: 50%; transform: translate(-50%, -50%); }
  .dot.done { filter: saturate(0.45); opacity: 0.45; }
  .swatch { display: inline-block; width: 18px; height: 10px; border-radius: 5px; box-sizing: border-box; flex: none; }
  .swatch.out { width: 10px; height: 10px; }
  .swatch.grow { height: 2px; background: var(--reap-grow); }
  .today { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: var(--error-color, #db4437); opacity: 0.8; }
  .more { position: absolute; top: 50%; transform: translateY(-50%); display: flex; color: var(--secondary-text-color); --mdc-icon-size: 16px; }
  .more.after { right: -15px; }
  .more.before { left: -15px; }
  .group-name { padding: 10px 16px 2px; font-size: 0.75em; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
  .plan-detail { margin: 2px 16px 8px; padding: 12px; border-radius: 12px; background: var(--secondary-background-color);
    display: flex; flex-direction: column; gap: 8px; }
  .steps { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; }
  .step { display: flex; align-items: center; gap: 8px; }
  .step-label { width: 110px; flex: none; }
  .done-mark { --mdc-icon-size: 16px; color: var(--success-color, #43a047); }
  .row-actions.gap { gap: 8px; flex-wrap: wrap; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.8em; padding: 10px 0 0; }
  .legend-item { display: inline-flex; align-items: center; gap: 6px; }
  .plan-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 28px 16px;
    margin: 4px 0; border: 1px dashed var(--divider-color); border-radius: 12px; }
  .plan-empty > ha-icon { --mdc-icon-size: 36px; color: var(--secondary-text-color); }
  @container (max-width: 760px) {
    .season-name.part { visibility: hidden; }
  }
  @container (max-width: 520px) {
    .plabel { width: 112px; }
    .psub { padding-left: 0; }
    .pname ha-icon { display: none; }
    .month .long { display: none; }
    .month .short { display: inline; }
    .season-name { font-size: 0.6em; letter-spacing: 0.02em; }
  }
`;

// ----- the locations card: a read-only view of each bed, tray or greenhouse -----

const LOCATIONS_DEFAULTS = {
  entity: "sensor.reap_plantings",
  locations: [],
  show_moisture: true,
  show_last_watered: true,
  show_watering: true,
  show_light: true,
  show_camera: true,
  show_snapshot: false,
  show_plantings: true,
  moisture_good: 30,
  moisture_low: 15,
};
const SNAPSHOT_SECONDS = 60;

function timeOfDay(date) {
  const opts = { hour: "numeric", minute: "2-digit" };
  try {
    return date.toLocaleTimeString(LOCALE, opts);
  } catch (err) {
    return date.toLocaleTimeString(undefined, opts);
  }
}

// "Today 7:10 AM", "Yesterday 6:02 PM", or "Nov 18, 6:02 PM".
function whenText(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(new Date()) - day(date)) / 86400000);
  if (diff === 0) return `Today ${timeOfDay(date)}`;
  if (diff === 1) return `Yesterday ${timeOfDay(date)}`;
  const local = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  return `${shortDate(local, date.getFullYear() !== new Date().getFullYear())}, ${timeOfDay(date)}`;
}

function isOn(state) {
  return !!state && ["on", "open", "opening"].includes(state.state);
}

class ReapLocationsCard extends ReapCard {
  setConfig(config) {
    this._confirmWater = null;
    super.setConfig({ ...LOCATIONS_DEFAULTS, ...config });
    // No crop list needed here.
    this._crops = this._crops || [];
  }

  static getConfigElement() {
    return document.createElement("reap-locations-card-editor");
  }

  static getStubConfig() {
    return { entity: "sensor.reap_plantings" };
  }

  getCardSize() {
    return 2 + Math.ceil(this._shown().length / 2) * 3;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  connectedCallback() {
    if (this._timer) return;
    // Camera snapshots refresh on their own; nothing else changes without a state change.
    this._timer = setInterval(() => {
      if (this._config && this._config.show_snapshot && this._config.show_camera) this._refreshSnapshots();
    }, SNAPSHOT_SECONDS * 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }

  _defaultTitle() {
    return "Garden locations";
  }

  _style() {
    return STYLE + PLANNER_STYLE + LOCATIONS_STYLE;
  }

  _shown() {
    const all = this._locations();
    const picked = (this._config.locations || []).map((n) => String(n).toLowerCase());
    if (!picked.length) return all;
    return picked.map((n) => all.find((l) => l.name.toLowerCase() === n || l.id === n)).filter(Boolean);
  }

  _watched() {
    const ids = [this._config.entity];
    for (const loc of this._shown()) {
      for (const key of ["soil_sensor", "light", "water"]) if (loc[key]) ids.push(loc[key]);
    }
    return ids;
  }

  async _service(domain, service, data) {
    try {
      await this._hass.connection.sendMessagePromise({ type: "call_service", domain, service, service_data: data });
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
      this._render();
    }
  }

  _setWater(entityId, on) {
    this._confirmWater = null;
    const domain = entityId.split(".")[0];
    if (domain === "valve") this._service("valve", on ? "open_valve" : "close_valve", { entity_id: entityId });
    else this._service("homeassistant", on ? "turn_on" : "turn_off", { entity_id: entityId });
    this._render();
  }

  async _logWatering(loc) {
    this._busy = true;
    this._render();
    try {
      await this._call("log_watering", { location: loc.id });
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false;
    this._render();
  }

  _refreshSnapshots() {
    if (!this.shadowRoot) return;
    for (const img of this.shadowRoot.querySelectorAll("img.snapshot")) {
      const st = this._hass && this._hass.states[img.dataset.entity];
      const url = st && st.attributes.entity_picture;
      if (url) img.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
    }
  }

  // Plantings still under way in a location: ones with open tasks.
  _growing(loc) {
    const name = loc.name.toLowerCase();
    return this._plantings().filter((p) => (p.location || "").toLowerCase() === name && (p.open_count || 0) > 0);
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    root.append(h("style", {}, this._style()));
    const card = h("ha-card", { header: this._config.title || this._defaultTitle() });
    const body = h("div", { class: "card-content" });
    card.append(body);
    root.append(card);
    if (!this._hass.states[this._config.entity]) {
      body.append(h("p", { class: "muted" }, `Entity ${this._config.entity} not found. Is Reap set up?`));
      return;
    }
    if (this._error) body.append(h("div", { class: "error" }, icon("mdi:alert-circle-outline"), this._error));
    const shown = this._shown();
    if (!shown.length) {
      body.append(h("p", { class: "muted" }, "No locations to show. Add them on the Reap card."));
      return;
    }
    body.append(h("div", { class: "loc-grid" }, shown.map((loc) => this._renderTile(loc))));
  }

  _renderTile(loc) {
    const cfg = this._config;
    const states = this._hass.states;
    const tile = h("div", { class: "loc-tile" });

    const head = h("div", { class: "loc-head" }, h("div", { class: "loc-name" }, loc.name));
    if (cfg.show_plantings) {
      const growing = this._growing(loc);
      if (growing.length) {
        const names = growing.map((p) => (p.variety ? `${p.crop_name} (${p.variety})` : p.crop_name));
        const icons = growing.slice(0, 6).map((p) => icon(p.icon || "mdi:sprout"));
        head.append(h("div", { class: "loc-crops", title: names.join(", ") }, icons,
          growing.length > 6 ? h("span", { class: "muted" }, `+${growing.length - 6}`) : null));
      }
    }
    tile.append(head);

    if (cfg.show_camera && cfg.show_snapshot && loc.camera && states[loc.camera] && states[loc.camera].attributes.entity_picture) {
      tile.append(h("button", { class: "snapshot-btn", title: `${loc.name} camera`, onclick: () => this._moreInfo(loc.camera) },
        h("img", { class: "snapshot", src: states[loc.camera].attributes.entity_picture, alt: `${loc.name} camera`, "data-entity": loc.camera })));
    }

    const rows = h("div", { class: "loc-rows" });
    if (cfg.show_moisture && loc.soil_sensor) {
      const st = states[loc.soil_sensor];
      const value = st ? parseFloat(st.state) : NaN;
      const ok = !Number.isNaN(value);
      rows.append(h("button", { class: "loc-row", onclick: () => this._moreInfo(loc.soil_sensor) },
        icon("mdi:water-percent", `loc-icon moisture ${ok ? moistureLevel(value, cfg) : "unknown"}`),
        h("span", { class: "loc-label muted" }, "Moisture"),
        h("span", { class: `loc-value moisture ${ok ? moistureLevel(value, cfg) : "unknown"}` }, ok ? `${Math.round(value)}%` : "Unavailable")));
    }

    const water = loc.water ? states[loc.water] : null;
    const running = isOn(water);
    if (cfg.show_last_watered) {
      let text = "Not recorded yet";
      if (running) text = `Running since ${timeOfDay(new Date(loc.last_watered || Date.now()))}`;
      else if (loc.last_watered) {
        const extra = loc.watered_by_hand ? "by hand" : loc.watered_minutes !== null && loc.watered_minutes !== undefined ? `${loc.watered_minutes} min` : null;
        text = [whenText(loc.last_watered), extra].filter(Boolean).join(" · ");
      }
      rows.append(h("div", { class: "loc-row" },
        icon(running ? "mdi:sprinkler-variant" : "mdi:watering-can-outline", `loc-icon${running ? " running" : ""}`),
        h("span", { class: "loc-label muted" }, "Watered"),
        h("span", { class: "loc-value" }, text)));
    }
    tile.append(rows);

    const actions = h("div", { class: "loc-actions" });
    if (cfg.show_watering) {
      if (loc.water) {
        actions.append(h("button", {
          class: running ? "primary" : "", disabled: !water || water.state === "unavailable",
          onclick: () => { if (running) this._setWater(loc.water, false); else { this._confirmWater = loc.id; this._render(); } },
        }, icon(running ? "mdi:stop" : "mdi:sprinkler-variant"), running ? "Stop" : "Water"));
      }
      if (!loc.water || !running) {
        actions.append(h("button", { disabled: this._busy, title: "Log a watering by hand", onclick: () => this._logWatering(loc) },
          icon("mdi:watering-can-outline"), "Watered"));
      }
    }
    if (cfg.show_light && loc.light) {
      const st = states[loc.light];
      const on = isOn(st);
      actions.append(h("button", {
        class: `icon-btn light${on ? " on" : ""}`, title: `${loc.name} light: ${st ? st.state : "unavailable"}`,
        "aria-label": `${loc.name} light`, disabled: !st || st.state === "unavailable",
        onclick: () => this._service("homeassistant", "toggle", { entity_id: loc.light }),
      }, icon(on ? "mdi:lightbulb-on" : "mdi:lightbulb-outline")));
    }
    if (cfg.show_camera && loc.camera) {
      actions.append(h("button", {
        class: "icon-btn", title: `${loc.name} camera`, "aria-label": `${loc.name} camera`,
        onclick: () => this._moreInfo(loc.camera),
      }, icon("mdi:cctv")));
    }
    if (actions.childElementCount) tile.append(actions);

    if (this._confirmWater === loc.id) {
      tile.append(h("div", { class: "confirm" }, `Start watering ${loc.name}?`,
        h("button", { onclick: () => { this._confirmWater = null; this._render(); } }, "Cancel"),
        h("button", { class: "primary", onclick: () => this._setWater(loc.water, true) }, "Start")));
    }
    return tile;
  }
}

const LOCATIONS_STYLE = `
  .loc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; padding-bottom: 8px; align-items: start; }
  .loc-tile { border: 1px solid var(--divider-color); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .loc-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .loc-name { font-weight: 500; font-size: 1.05em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .loc-crops { display: flex; align-items: center; gap: 2px; color: var(--secondary-text-color); --mdc-icon-size: 18px; font-size: 0.8em; flex: none; }
  .loc-rows { display: flex; flex-direction: column; gap: 4px; }
  button.loc-row, .loc-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; border: none; border-radius: 0; background: none;
    color: inherit; font: inherit; text-align: left; width: 100%; font-size: 0.9em; }
  button.loc-row { cursor: pointer; }
  .loc-label { width: 70px; flex: none; }
  .loc-value { flex: 1; min-width: 0; }
  .loc-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); flex: none; }
  .loc-icon.running { color: var(--info-color, var(--primary-color)); }
  .moisture.good { color: var(--success-color, #43a047); }
  .moisture.low { color: var(--warning-color, #ffa600); }
  .moisture.dry { color: var(--error-color, #db4437); }
  .loc-value.moisture { font-weight: 500; }
  .loc-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .loc-actions .icon-btn.light.on { color: var(--state-light-active-color, var(--amber-color, #ffc107)); }
  .snapshot-btn { padding: 0; border: none; border-radius: 8px; overflow: hidden; background: var(--secondary-background-color); display: block; width: 100%; }
  .snapshot { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; }
  .loc-tile .confirm { margin: 0; }
`;

const STYLE = `
  .card-content { padding: 0 16px 8px; }
  .list { display: flex; flex-direction: column; }
  .row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--divider-color); }
  .row:last-child { border-bottom: none; }
  .crop-icon { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.15); color: var(--primary-color); flex: none; }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }
  .name { font-weight: 500; display: flex; align-items: center; gap: 4px; }
  .name ha-icon.method { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .small { font-size: 0.875em; display: flex; align-items: center; gap: 4px; }
  .small ha-icon { --mdc-icon-size: 16px; flex: none; }
  .muted { color: var(--secondary-text-color); }
  .next { color: var(--primary-text-color); margin-top: 2px; }
  .row-actions { display: flex; flex: none; }
  .icon-btn { background: none; border: none; color: var(--secondary-text-color); cursor: pointer; padding: 6px; border-radius: 50%; }
  .icon-btn:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; padding: 8px 16px 16px; flex-wrap: wrap; }
  .form .actions { padding: 12px 0 0; }
  .tabs { display: flex; gap: 6px; }
  .notice { padding: 6px 8px; border-radius: 8px; background: var(--secondary-background-color); }
  .notice span { flex: 1; }
  .tabs .tab.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .picks { max-height: 320px; overflow-y: auto; border: 1px solid var(--divider-color); border-radius: 8px; padding: 0 8px; }
  .pick { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--divider-color); cursor: pointer; }
  .pick:last-child { border-bottom: none; }
  .pick[hidden] { display: none; }
  .pick > ha-icon { color: var(--primary-color); flex: none; }
  .varieties { display: flex; flex-direction: column; gap: 6px; }
  .field-label { font-size: 0.9em; color: var(--secondary-text-color); }
  .variety { display: flex; gap: 6px; align-items: center; }
  .variety input { font: inherit; flex: 1; min-width: 0; padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); }
  button { font: inherit; display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 18px; cursor: pointer;
    border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); }
  button ha-icon { --mdc-icon-size: 18px; }
  button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.danger { background: var(--error-color); border-color: var(--error-color); color: var(--text-primary-color, #fff); }
  .sensors { display: flex; gap: 6px; flex: none; align-items: center; }
  .chip { padding: 2px 8px; border-radius: 12px; font-size: 0.85em; gap: 2px; border: none;
    background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .chip.moisture.good { color: var(--success-color, #43a047); }
  .chip.moisture.low { color: var(--warning-color, #ffa600); }
  .chip.moisture.dry { color: var(--error-color, #db4437); }
  .chip.light { padding: 4px; border-radius: 50%; }
  .chip.light.on { color: var(--state-light-active-color, var(--amber-color, #ffc107)); }
  button:disabled { opacity: 0.5; cursor: default; }
  .confirm { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px; margin-bottom: 8px; border-radius: 8px;
    background: var(--secondary-background-color); font-size: 0.9em; }
  .form { display: flex; flex-direction: column; gap: 10px; }
  .form-title { font-weight: 500; font-size: 1.1em; display: flex; align-items: center; gap: 8px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
  .field { display: flex; flex-direction: column; gap: 4px; font-size: 0.85em; color: var(--secondary-text-color); }
  .field input, .field select { font: inherit; font-size: 1rem; padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); min-width: 0; }
  .preview { max-height: 260px; overflow: auto; padding: 8px; border-radius: 8px; background: var(--secondary-background-color);
    display: flex; flex-direction: column; gap: 4px; }
  .check { display: flex; align-items: center; gap: 8px; font-size: 0.9em; }
  .range { display: grid; grid-template-columns: minmax(110px, 1fr) 1fr 1fr; gap: 8px; align-items: end; }
  .md { display: flex; gap: 4px; }
  .md select { font: inherit; font-size: 1rem; padding: 8px 4px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); min-width: 0; flex: 1; }
  .range-label { font-size: 0.9em; padding-bottom: 10px; }
  .search { font: inherit; padding: 8px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); }
  .list > div[hidden] { display: none; }
  .list > div:not(:last-child) > .row { border-bottom: 1px solid var(--divider-color); }
  .season { border-top: 1px solid var(--divider-color); padding-top: 4px; }
  .season summary { cursor: pointer; font-weight: 500; padding: 8px 0; }
  .season > .range { margin-bottom: 8px; }
  .removed summary { cursor: pointer; color: var(--secondary-text-color); padding: 8px 0; }
  .crop-icon.small-icon { width: 36px; height: 36px; --mdc-icon-size: 22px; }
  .error { color: var(--error-color); display: flex; align-items: center; gap: 6px; padding: 8px 0; }
  .info .error { padding: 2px 0; }
`;

const EDITOR_SCHEMA = [
  { name: "title", selector: { text: {} } },
  { name: "entity", selector: { entity: { domain: "sensor", integration: "reap" } } },
  {
    type: "grid", name: "", schema: [
      { name: "show_info", selector: { boolean: {} } },
      { name: "show_next", selector: { boolean: {} } },
      { name: "show_sensors", selector: { boolean: {} } },
      { name: "editable", selector: { boolean: {} } },
      { name: "show_done", selector: { boolean: {} } },
    ],
  },
  { name: "icon_size", selector: { number: { min: 16, max: 72, step: 4, mode: "slider", unit_of_measurement: "px" } } },
  { name: "planner_path", selector: { text: {} } },
  {
    type: "grid", name: "", schema: [
      { name: "moisture_good", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
      { name: "moisture_low", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
    ],
  },
];
const EDITOR_LABELS = {
  title: "Title",
  entity: "Plantings sensor",
  show_info: "Show details row",
  show_next: "Show next task row",
  show_sensors: "Show soil moisture and light",
  editable: "Edit mode (add, edit and remove)",
  show_done: "Show finished plantings",
  icon_size: "Icon size",
  planner_path: "Planner view path, such as /lovelace/plan (adds a Plan button)",
  moisture_good: "Moisture is green above",
  moisture_low: "Moisture is red below",
};

const PLANNER_SCHEMA = [
  { name: "title", selector: { text: {} } },
  { name: "entity", selector: { entity: { domain: "sensor", integration: "reap" } } },
  {
    name: "group_by", selector: { select: { mode: "dropdown", options: [
      { value: "date", label: "By date" }, { value: "crop", label: "By crop" },
      { value: "location", label: "By location" }] } },
  },
  { name: "max_height", selector: { number: { min: 0, max: 2000, step: 20, mode: "box", unit_of_measurement: "px" } } },
  { name: "editable", selector: { boolean: {} } },
];
const PLANNER_LABELS = {
  title: "Title",
  entity: "Plantings sensor",
  group_by: "Group plantings",
  max_height: "Chart height before it scrolls (0 for no limit)",
  editable: "Edit mode (add, edit, remove and copy)",
};

class ReapCardEditor extends HTMLElement {
  get _schema() { return EDITOR_SCHEMA; }

  get _labels() { return EDITOR_LABELS; }

  get _defaults() { return CARD_DEFAULTS; }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    else this._render();
  }

  _render() {
    if (!this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.schema = this._schema;
      this._form.computeLabel = (s) => this._labels[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        // Only keep options that differ from the defaults in the card's YAML.
        const config = {};
        for (const [key, value] of Object.entries(ev.detail.value)) {
          if (key === "type" || key === "entity" || this._defaults[key] !== value) config[key] = value;
        }
        this.dispatchEvent(new CustomEvent("config-changed", {
          bubbles: true, composed: true, detail: { config },
        }));
      });
      this.append(this._form);
    }
    if (this._hass) this._form.hass = this._hass;
    this._form.data = { ...this._defaults, ...this._config };
  }
}

const LOCATIONS_LABELS = {
  title: "Title",
  entity: "Plantings sensor",
  locations: "Locations to show (all if none picked)",
  show_moisture: "Soil moisture",
  show_last_watered: "Last watered",
  show_watering: "Watering buttons",
  show_light: "Light switch",
  show_camera: "Camera button",
  show_snapshot: "Camera snapshot",
  show_plantings: "What's planted there",
  moisture_good: "Moisture is green above",
  moisture_low: "Moisture is red below",
};

class ReapLocationsCardEditor extends ReapCardEditor {
  get _schema() {
    const state = this._hass && this._config && this._hass.states[this._config.entity || LOCATIONS_DEFAULTS.entity];
    const names = ((state && state.attributes.locations) || []).map((l) => l.name);
    return [
      { name: "title", selector: { text: {} } },
      { name: "entity", selector: { entity: { domain: "sensor", integration: "reap" } } },
      { name: "locations", selector: { select: { multiple: true, mode: "list", options: names } } },
      {
        type: "grid", name: "", schema: ["show_moisture", "show_last_watered", "show_watering", "show_light",
          "show_camera", "show_snapshot", "show_plantings"].map((name) => ({ name, selector: { boolean: {} } })),
      },
      {
        type: "grid", name: "", schema: [
          { name: "moisture_good", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
          { name: "moisture_low", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
        ],
      },
    ];
  }

  get _labels() { return LOCATIONS_LABELS; }

  get _defaults() { return LOCATIONS_DEFAULTS; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
      // The location list comes from Home Assistant, so fill it in once known.
      if (first) this._form.schema = this._schema;
    } else this._render();
  }
}

class ReapPlannerCardEditor extends ReapCardEditor {
  get _schema() { return PLANNER_SCHEMA; }

  get _labels() { return PLANNER_LABELS; }

  get _defaults() { return PLANNER_DEFAULTS; }
}

if (!customElements.get("reap-card-editor")) {
  customElements.define("reap-card-editor", ReapCardEditor);
}
if (!customElements.get("reap-locations-card-editor")) {
  customElements.define("reap-locations-card-editor", ReapLocationsCardEditor);
}
if (!customElements.get("reap-planner-card-editor")) {
  customElements.define("reap-planner-card-editor", ReapPlannerCardEditor);
}

if (!customElements.get("reap-card")) {
  customElements.define("reap-card", ReapCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "reap-card",
    name: "Reap",
    description: "Reap what you Sow. Your plantings with their next task, soil moisture and lights. Add, edit and remove plantings and locations.",
    preview: true,
  });
}
if (!customElements.get("reap-planner-card")) {
  customElements.define("reap-planner-card", ReapPlannerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "reap-planner-card",
    name: "Reap planner",
    description: "Reap's season chart: one growing year of plantings from sowing to harvest. Switch years and copy a plan to the next season.",
    preview: true,
  });
}
if (!customElements.get("reap-locations-card")) {
  customElements.define("reap-locations-card", ReapLocationsCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "reap-locations-card",
    name: "Reap locations",
    description: "Reap's beds, trays and greenhouses at a glance: soil moisture, when each was last watered, watering, lights and cameras.",
    preview: true,
  });
}
