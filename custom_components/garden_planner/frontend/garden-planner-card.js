/*
 * Garden Planner card: lists plantings with their icons and next task, and
 * adds, edits and removes them through the garden_planner actions.
 *
 * type: custom:garden-planner-card
 * entity: sensor.garden_planner_plantings   # optional
 * title: Garden                              # optional
 * show_done: false                           # optional, show finished plantings
 */

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

function shortDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function defaultYear() {
  const now = new Date();
  return now.getMonth() < 8 ? now.getFullYear() : now.getFullYear() + 1;
}

class GardenPlannerCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.garden_planner_plantings", show_done: false, ...config };
    this._mode = null; // null | "add" | "edit"
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
    if (!this._crops && !this._loadingCrops) this._loadCrops();
    const entity = this._config && this._config.entity;
    // Only redraw when the plantings change, so typing in the form isn't interrupted.
    if (!old || !entity || old.states[entity] !== hass.states[entity]) {
      if (!this._mode) this._render();
    }
  }

  getCardSize() {
    return 3 + this._plantings().length;
  }

  static getStubConfig() {
    return { entity: "sensor.garden_planner_plantings" };
  }

  async _call(service, data, response = false) {
    const msg = { type: "call_service", domain: "garden_planner", service, service_data: data };
    if (response) msg.return_response = true;
    const result = await this._hass.connection.sendMessagePromise(msg);
    return response ? result.response : result;
  }

  async _loadCrops() {
    this._loadingCrops = true;
    try {
      const res = await this._call("list_crops", {}, true);
      this._crops = res.crops;
    } catch (err) {
      this._error = `Couldn't load the crop list: ${err.message || err}`;
    }
    this._loadingCrops = false;
    this._render();
  }

  _plantings() {
    const state = this._hass && this._hass.states[this._config.entity];
    if (!state) return [];
    return state.attributes.plantings || [];
  }

  _crop(key) {
    return (this._crops || []).find((c) => c.key === key);
  }

  // ----- actions -----

  _startAdd() {
    const first = (this._crops || [])[0];
    this._mode = "add";
    this._editing = null;
    this._form = { year: defaultYear() };
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
      if (this._mode === "add") {
        await this._call("add_planting", payload);
      } else {
        await this._call("update_planting", { planting_id: this._editing, ...payload });
      }
      if (this._form.save_defaults) {
        const defaults = { crop: payload.crop };
        for (const k of DEFAULT_KEYS) {
          if (payload[k] !== undefined && payload[k] !== "") defaults[k] = payload[k];
        }
        await this._call("set_crop_defaults", defaults);
        await this._loadCrops();
      }
      this._mode = null;
      this._form = {};
      this._preview = null;
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

  _cancel() {
    this._mode = null;
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
      body.append(h("p", { class: "muted" }, `Entity ${this._config.entity} not found. Is Garden Planner set up?`));
      return;
    }
    if (this._error) body.append(h("div", { class: "error" }, icon("mdi:alert-circle-outline"), this._error));

    if (this._mode) {
      body.append(this._renderForm());
      return;
    }

    const plantings = this._plantings()
      .map((p) => ({ ...p, open: (p.tasks || []).filter((t) => !t.done_on) }))
      .filter((p) => this._config.show_done || p.open.length)
      .sort((a, b) => ((a.open[0] || {}).due || "9999").localeCompare((b.open[0] || {}).due || "9999"));

    if (!plantings.length) {
      body.append(h("p", { class: "muted" }, "Nothing planned yet. Add your first planting."));
    }
    const list = h("div", { class: "list" });
    for (const p of plantings) list.append(this._renderRow(p));
    body.append(list);

    const actions = h("div", { class: "actions" },
      h("button", { class: "primary", onclick: () => this._startAdd(), disabled: !this._crops },
        icon("mdi:plus"), "Add planting"));
    card.append(actions);
  }

  _renderRow(p) {
    const crop = this._crop(p.crop);
    const next = p.open[0];
    const name = p.variety ? `${p.crop_name} (${p.variety})` : p.crop_name;
    const sowings = new Set((p.tasks || []).map((t) => t.succession)).size;
    const details = [
      METHOD_LABELS[p.method] || p.method,
      p.season && p.season !== "spring" ? p.season : null,
      String(p.year),
      sowings > 1 ? `${sowings} sowings, every ${p.succession_days} days` : null,
      p.location,
      p.quantity,
    ].filter(Boolean).join(" · ");

    const row = h("div", { class: "row" },
      h("div", { class: "crop-icon" }, icon(p.icon || (crop && crop.icon) || "mdi:sprout")),
      h("div", { class: "info" },
        h("div", { class: "name" }, name, " ", icon(METHOD_ICONS[p.method] || "mdi:sprout", "method")),
        h("div", { class: "muted small" }, details),
        next
          ? h("div", { class: "next small" }, icon(next.icon || "mdi:calendar"), `${shortDate(next.due)}: ${next.summary}`)
          : h("div", { class: "muted small" }, icon("mdi:check"), "All done")),
      h("div", { class: "row-actions" },
        h("button", { class: "icon-btn", title: "Edit", onclick: () => this._startEdit(p) }, icon("mdi:pencil")),
        h("button", { class: "icon-btn", title: "Remove", onclick: () => { this._confirmDelete = p.id; this._render(); } }, icon("mdi:delete-outline"))));

    if (this._confirmDelete === p.id) {
      return h("div", {}, row,
        h("div", { class: "confirm" },
          `Remove ${name}? Its open tasks come off your list.`,
          h("button", { onclick: () => { this._confirmDelete = null; this._render(); } }, "Keep"),
          h("button", { class: "danger", disabled: this._busy, onclick: () => this._delete(p.id) }, "Remove")));
    }
    return row;
  }

  _input(key, label, type = "text", extra = {}) {
    const value = this._form[key] === undefined || this._form[key] === null ? "" : this._form[key];
    return h("label", { class: "field" }, h("span", {}, label),
      h("input", {
        type, value, ...extra,
        oninput: (e) => { this._form[key] = e.target.value; this._preview = null; },
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
      this._input("year", "Year", "number", { min: 2024, max: 2100 }),
      this._input("start_date", "Start date (optional)", "date"),
      this._input("succession_days", "Repeat every (days)", "number", { min: 0, max: 365 }),
      this._input("succession_count", "Number of sowings", "number", { min: 1, max: 200 }),
      this._input("succession_until", "Repeat until", "date"),
      this._input("variety", "Variety"),
      this._input("quantity", "Quantity", "text", { placeholder: "6 cells" }),
      this._input("location", "Location", "text", { placeholder: "Bed 3" })));
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
        list.append(h("div", { class: "small" }, icon(t.icon || "mdi:calendar"), `${shortDate(t.due)}, ${t.due.slice(0, 4)}: ${t.summary}`));
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
  .info { flex: 1; min-width: 0; }
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
  button.danger { background: var(--error-color); border-color: var(--error-color); color: #fff; }
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
  .error { color: var(--error-color); display: flex; align-items: center; gap: 6px; padding: 8px 0; }
`;

if (!customElements.get("garden-planner-card")) {
  customElements.define("garden-planner-card", GardenPlannerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "garden-planner-card",
    name: "Garden Planner",
    description: "Your plantings with their next task. Add, edit and remove plantings.",
  });
}
