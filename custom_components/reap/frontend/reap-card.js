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
 */

const CARD_DEFAULTS = {
  entity: "sensor.reap_plantings",
  show_done: false,
  show_info: true,
  show_next: true,
  show_sensors: true,
  icon_size: 40,
  editable: true,
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

function moistureLevel(value) {
  if (value > 30) return "good";
  if (value >= 15) return "low";
  return "dry";
}

const LIGHT_DOMAINS = ["light.", "switch.", "input_boolean."];
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
    this._form = { year: "" };
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
        await this._call("add_planting", payload);
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
    this._mode = "location";
    this._editing = loc ? loc.id : null;
    this._form = loc
      ? { name: loc.name, soil_sensor: loc.soil_sensor || "", light: loc.light || "" }
      : { name: "", soil_sensor: "", light: "" };
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
    root.append(h("style", {}, STYLE));

    const state = this._hass.states[this._config.entity];
    const card = h("ha-card", { header: this._config.title || "Garden" });
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
    if (this._mode) {
      body.append(this._renderForm());
      return;
    }

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
        class: `chip moisture ${ok ? moistureLevel(value) : "unknown"}`,
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

  _entityOptions(filter, current) {
    const ids = Object.keys(this._hass.states).filter((id) => filter(id, this._hass.states[id]));
    if (current && !ids.includes(current)) ids.push(current);
    const label = (id) => {
      const st = this._hass.states[id];
      const name = st && st.attributes.friendly_name;
      return name ? `${name} (${id})` : id;
    };
    return [["", "None"], ...ids.sort().map((id) => [id, label(id)])];
  }

  _renderLocationForm() {
    const form = h("div", { class: "form" });
    form.append(h("div", { class: "form-title" }, icon("mdi:map-marker-outline"),
      this._editing ? `Edit ${this._form.name || "location"}` : "Add a location"));
    form.append(this._input("name", "Name", "text", { placeholder: "Bed 3" }));
    const soil = (id, st) => id.startsWith("sensor.") && (
      st.attributes.device_class === "moisture" ||
      (st.attributes.unit_of_measurement === "%" && /soil|moist/i.test(`${id} ${st.attributes.friendly_name || ""}`)));
    form.append(this._select("soil_sensor", "Soil moisture sensor (optional)",
      this._entityOptions(soil, this._form.soil_sensor)));
    form.append(this._select("light", "Light (optional)",
      this._entityOptions((id) => LIGHT_DOMAINS.some((d) => id.startsWith(d)), this._form.light)));
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
    form.append(h("div", { class: "form-title" },
      icon((crop && crop.icon) || "mdi:sprout"),
      this._mode === "add" ? "Add a planting" : `Edit ${crop ? crop.name : this._form.crop}`));

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
      this._input("variety", "Variety"),
      this._input("quantity", "Quantity", "text", { placeholder: "6 cells" }),
      this._locationSelect()));
    form.append(this._input("notes", "Notes"));
    form.append(h("label", { class: "check" },
      h("input", {
        type: "checkbox", checked: !!this._form.save_defaults,
        onchange: (e) => { this._form.save_defaults = e.target.checked; },
      }),
      "Save method, repeat, sowings, quantity and location as the default for this crop"));
    form.append(h("p", { class: "muted small" },
      "Start date is the transplant date for indoor starts, or the first sowing for direct sowing. Leave it empty to use the crop's usual window."));

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
        icon("mdi:content-save-outline"), this._mode === "add" ? "Add" : "Save")));
    return form;
  }
}

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
};

class ReapCardEditor extends HTMLElement {
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
      this._form.schema = EDITOR_SCHEMA;
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        // Only keep options that differ from the defaults in the card's YAML.
        const config = {};
        for (const [key, value] of Object.entries(ev.detail.value)) {
          if (key === "type" || key === "entity" || CARD_DEFAULTS[key] !== value) config[key] = value;
        }
        this.dispatchEvent(new CustomEvent("config-changed", {
          bubbles: true, composed: true, detail: { config },
        }));
      });
      this.append(this._form);
    }
    if (this._hass) this._form.hass = this._hass;
    this._form.data = { ...CARD_DEFAULTS, ...this._config };
  }
}

if (!customElements.get("reap-card-editor")) {
  customElements.define("reap-card-editor", ReapCardEditor);
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
