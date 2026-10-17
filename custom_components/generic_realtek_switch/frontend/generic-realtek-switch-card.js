/*
 * Generic Realtek Switch – port strip card.
 *
 * Shows the ports of one switch as a row of tiles, like the port strip of the
 * RTLPlayground web interface: colour by link speed, "down" and "off" greyed
 * out. A click opens the details of the port. Served and loaded by the
 * integration itself, nothing to add under Resources.
 *
 *   type: custom:generic-realtek-switch-card
 *   device: <device id>     # chosen in the card editor
 *   title: Keller           # optional, default: the device name
 */
const DOMAIN = "generic_realtek_switch";
const CARD = "generic-realtek-switch-card";

// Link speed colours of the RTLPlayground web interface (light / dark theme)
const COLORS = {
  light: { slow: "#b58900", g1: "#159744", g25: "#0d9488", g10: "#2563eb" },
  dark: { slow: "#d29922", g1: "#3fb950", g25: "#2dd4bf", g10: "#58a6ff" },
};
const SPEED = {
  "10m": ["10M", "slow"],
  "100m": ["100M", "slow"],
  "1000m": ["1G", "g1"],
  "2500m": ["2.5G", "g25"],
  "5000m": ["5G", "g25"],
  "10g": ["10G", "g10"],
};
const TEXT = {
  de: { down: "getrennt", off: "aus", na: "–", up: "verbunden", none: "Kein Switch gewählt", device: "Switch", title: "Titel (optional)", learned: "Gelernte Geräte" },
  en: { down: "down", off: "off", na: "–", up: "connected", none: "No switch selected", device: "Switch", title: "Title (optional)", learned: "Devices learned" },
};

function text(hass) {
  const lang = ((hass && (hass.locale?.language || hass.language)) || "en").slice(0, 2);
  return TEXT[lang] || TEXT.en;
}

// Port sensors ("Port N") of a device, sorted by port number
function portEntities(hass, deviceId) {
  return Object.values(hass.entities || {})
    .filter((e) => e.device_id === deviceId && e.platform === DOMAIN && e.translation_key === "port")
    .map((e) => {
      const st = hass.states[e.entity_id];
      const m = e.entity_id.match(/_port_(\d+)$/);
      const num = Number(st?.attributes?.port ?? (m ? m[1] : NaN));
      return { id: e.entity_id, num, st };
    })
    .filter((p) => !Number.isNaN(p.num))
    .sort((a, b) => a.num - b.num);
}

function firstDevice(hass) {
  const e = Object.values(hass.entities || {}).find(
    (x) => x.platform === DOMAIN && x.translation_key === "port" && x.device_id
  );
  return e ? e.device_id : undefined;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

class GenericRealtekSwitchCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._sig = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 2;
  }

  getGridOptions() {
    return { columns: 12, rows: 2, min_columns: 6, min_rows: 2 };
  }

  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    return { device: firstDevice(hass) };
  }

  _render() {
    const hass = this._hass;
    if (!hass || !this._config) return;
    const t = text(hass);
    const ports = this._config.device ? portEntities(hass, this._config.device) : [];
    const dev = hass.devices?.[this._config.device];
    const title = this._config.title || dev?.name_by_user || dev?.name || "";
    const dark = !!hass.themes?.darkMode;

    // Only redraw when something visible changed
    const sig = JSON.stringify([title, dark, t.up, ports.map((p) => [p.id, p.st?.state, p.st?.attributes?.port_name, p.st?.attributes?.learned_macs])]);
    if (sig === this._sig) return;
    this._sig = sig;

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const col = COLORS[dark ? "dark" : "light"];
    let up = 0;
    const tiles = ports.map((p) => {
      const state = p.st?.state;
      let cls = "port", label, color = "";
      if (SPEED[state]) {
        up++;
        label = SPEED[state][0];
        color = col[SPEED[state][1]];
        cls += " up";
      } else if (state === "disabled") {
        label = t.off;
        cls += " dis";
      } else if (state === "disconnected") {
        label = t.down;
      } else {
        label = t.na;
        cls += " dis";
      }
      const a = p.st?.attributes || {};
      const tip = [`Port ${p.num}`, a.port_name, a.sfp_module, a.learned_macs != null ? `${t.learned}: ${a.learned_macs}` : ""]
        .filter(Boolean)
        .join(" · ");
      return `<div class="${cls}" style="${color ? `--pc:${color}` : ""}" data-id="${esc(p.id)}" title="${esc(tip)}" role="button" tabindex="0">
        <span class="pn">${p.num}</span><span class="jack"></span><span class="ps">${esc(label)}</span></div>`;
    });

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 14px; }
        .head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; }
        .title { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .count { font-size: 12px; color: var(--secondary-text-color); }
        .strip { display: flex; flex-wrap: wrap; gap: 6px; }
        .port {
          width: 44px; border: 2px solid var(--divider-color); border-radius: 7px; padding: 3px 0 2px;
          text-align: center; cursor: pointer; background: var(--secondary-background-color);
          color: var(--primary-text-color); box-sizing: border-box; outline: none;
        }
        .port:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
        .pn { font-weight: 650; font-size: 12px; display: block; }
        .ps { font-size: 9px; color: var(--secondary-text-color); display: block; line-height: 1.2; }
        .jack {
          display: block; width: 16px; height: 10px; margin: 2px auto 1px; border-radius: 2px;
          border: 2px solid var(--secondary-text-color); border-top-width: 4px; opacity: .55; box-sizing: content-box;
        }
        .port.up { border-color: var(--pc); background: color-mix(in srgb, var(--pc) 12%, var(--secondary-background-color)); }
        .port.up .jack { border-color: var(--pc); opacity: 1; }
        .port.up .ps { color: var(--pc); font-weight: 600; }
        .port.dis { opacity: .45; border-style: dashed; }
        .none { color: var(--secondary-text-color); font-size: 14px; }
      </style>
      <ha-card>
        ${title || ports.length ? `<div class="head"><span class="title">${esc(title)}</span>${ports.length ? `<span class="count">${up} / ${ports.length} ${esc(t.up)}</span>` : ""}</div>` : ""}
        ${ports.length ? `<div class="strip">${tiles.join("")}</div>` : `<div class="none">${esc(t.none)}</div>`}
      </ha-card>`;

    this.shadowRoot.querySelectorAll(".port").forEach((el) => {
      const open = () =>
        this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: el.dataset.id } }));
      el.addEventListener("click", open);
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
  }
}

class GenericRealtekSwitchCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...this._config, ...ev.detail.value };
        if (!config.title) delete config.title;
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { bubbles: true, composed: true, detail: { config } }));
      });
      this.appendChild(this._form);
    }
    const t = text(this._hass);
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "device", required: true, selector: { device: { integration: DOMAIN } } },
      { name: "title", selector: { text: {} } },
    ];
    this._form.computeLabel = (s) => (s.name === "device" ? t.device : t.title);
    this._form.data = this._config;
  }
}

if (!customElements.get(CARD)) {
  customElements.define(CARD, GenericRealtekSwitchCard);
  customElements.define(`${CARD}-editor`, GenericRealtekSwitchCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD,
    name: "Generic Realtek Switch",
    description: (navigator.language || "").startsWith("de")
      ? "Port-Leiste eines Switches: Geschwindigkeit pro Port, Klick für Details."
      : "Port strip of a switch: link speed per port, click for details.",
    preview: true,
  });
}
