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
 *   expected:               # optional: ports that should run at least this fast
 *     2: 2.5G
 *     8: 2.5G
 *   show_reboot: true       # optional: actions in the header, all on by default
 *   show_update: true
 *   show_web: true
 *   port_toggle: false      # optional: a long press turns a port on or off,
 *                           # after asking (needs the "Port N enabled" switch)
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
// How long a port tile has to be held before it asks to turn the port on or off
const HOLD_MS = 1000;
// Speed in Mbit/s per port state, to compare with the expected speed
const MBIT = { "10m": 10, "100m": 100, "1000m": 1000, "2500m": 2500, "5000m": 5000, "10g": 10000 };
const TEXT = {
  de: {
    down: "getrennt", off: "aus", na: "–", up: "verbunden", none: "Kein Switch gewählt", device: "Switch",
    title: "Titel (optional)", learned: "Gelernte Geräte", below: (n) => `${n} unter Soll`,
    want: (w, is) => `Soll ${w}, ist ${is}`,
    expected: "Soll-Geschwindigkeit pro Port (optional, z. B. 2:2.5G, 8:2.5G)",
    reboot: "Neustart", reboot_q: (n) => `Switch ${n} wirklich neu starten? Die angeschlossenen Geräte sind kurz offline.`,
    update: "Update", updating: "Update läuft…", update_t: (v) => `Firmware-Update auf ${v} verfügbar`,
    web: "Weboberfläche öffnen",
    show_reboot: "Neustart-Knopf", show_update: "Hinweis auf Firmware-Update", show_web: "Link zur Weboberfläche",
    port_toggle: "Ports per langem Drücken ein-/ausschalten", hold: "lange drücken: ein/aus",
    off_q: (p, n) => `Port ${p} von ${n} ausschalten?\n\nDie Geräte an diesem Port verlieren die Verbindung. `
      + "Ist es der Port, über den der Switch mit dem Netz verbunden ist, bleibt der Switch bis zum nächsten Neustart unerreichbar.",
    on_q: (p, n) => `Port ${p} von ${n} einschalten?`,
    no_switch: (p, n) => `Der Schalter „Port ${p} aktiv“ ist in Home Assistant deaktiviert.\n\n`
      + `Aktivieren unter Einstellungen → Geräte & Dienste → Generic Realtek Switch → ${n} → Entitäten.`,
    no_sfp: "SFP-Ports lassen sich nicht ein- und ausschalten.",
    cancel: "Abbrechen", ok: "OK", do_off: "Ausschalten", do_on: "Einschalten", do_reboot: "Neu starten",
  },
  en: {
    down: "down", off: "off", na: "–", up: "connected", none: "No switch selected", device: "Switch",
    title: "Title (optional)", learned: "Devices learned", below: (n) => `${n} below target`,
    want: (w, is) => `expected ${w}, is ${is}`,
    expected: "Expected speed per port (optional, e.g. 2:2.5G, 8:2.5G)",
    reboot: "Restart", reboot_q: (n) => `Really restart switch ${n}? The connected devices are offline for a moment.`,
    update: "Update", updating: "Updating…", update_t: (v) => `Firmware update to ${v} available`,
    web: "Open web interface",
    show_reboot: "Restart button", show_update: "Firmware update notice", show_web: "Link to the web interface",
    port_toggle: "Turn ports on/off by a long press", hold: "long press: on/off",
    off_q: (p, n) => `Turn off port ${p} of ${n}?\n\nThe devices on this port lose their connection. `
      + "If it is the port that connects the switch to the network, the switch stays unreachable until its next restart.",
    on_q: (p, n) => `Turn on port ${p} of ${n}?`,
    no_switch: (p, n) => `The switch "Port ${p} enabled" is disabled in Home Assistant.\n\n`
      + `Enable it under Settings → Devices & services → Generic Realtek Switch → ${n} → Entities.`,
    no_sfp: "SFP ports cannot be turned on and off.",
    cancel: "Cancel", ok: "OK", do_off: "Turn off", do_on: "Turn on", do_reboot: "Restart",
  },
};

// "2.5G", "2500m", "1g", 2500 → Mbit/s; NaN if not a speed
function toMbit(v) {
  const m = String(v ?? "").trim().toLowerCase().match(/^(\d+(?:\.\d+)?)\s*([mg])?(?:bit)?$/);
  if (!m) return NaN;
  return Math.round(Number(m[1]) * (m[2] === "g" ? 1000 : 1));
}

function speedLabel(mbit) {
  return mbit >= 1000 ? `${mbit / 1000}G` : `${mbit}M`;
}

// {2: "2.5G"} or "2:2.5G, 8:2.5G" → {2: 2500, 8: 2500}
function parseExpected(x) {
  const out = {};
  const pairs = typeof x === "string"
    ? x.split(/[,;\s]+/).filter(Boolean).map((p) => p.split(/[:=]/))
    : Object.entries(x || {});
  for (const [port, speed] of pairs) {
    const n = parseInt(port, 10), mbit = toMbit(speed);
    if (n > 0 && mbit > 0) out[n] = mbit;
  }
  return out;
}

function expectedText(x) {
  return Object.entries(parseExpected(x)).map(([p, m]) => `${p}:${speedLabel(m)}`).join(", ");
}

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

// "Port N enabled" switches of a device: port number → entity id
function portSwitches(hass, deviceId) {
  const out = {};
  for (const e of Object.values(hass.entities || {})) {
    if (e.device_id !== deviceId || e.platform !== DOMAIN || e.translation_key !== "port_enabled") continue;
    const m = e.entity_id.match(/_port_(\d+)_enabled$/);
    if (m && hass.states[e.entity_id]) out[Number(m[1])] = e.entity_id;
  }
  return out;
}

// Entity of the device by its translation key, e.g. the reboot button
function deviceEntity(hass, deviceId, domain, key) {
  const e = Object.values(hass.entities || {}).find(
    (x) => x.device_id === deviceId && x.platform === DOMAIN && x.translation_key === key && x.entity_id.startsWith(`${domain}.`)
  );
  return e ? e.entity_id : undefined;
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
    const expected = parseExpected(this._config.expected);
    const cfg = this._config;
    const rebootId = cfg.show_reboot !== false ? deviceEntity(hass, cfg.device, "button", "reboot") : undefined;
    const updateId = cfg.show_update !== false ? deviceEntity(hass, cfg.device, "update", "firmware_update") : undefined;
    const upd = updateId ? hass.states[updateId] : undefined;
    const updateOn = upd && (upd.state === "on" || upd.attributes?.in_progress);
    const web = cfg.show_web !== false ? dev?.configuration_url : undefined;
    const toggle = cfg.port_toggle === true;
    const switches = toggle ? portSwitches(hass, cfg.device) : {};
    this._toggle = { on: toggle, switches, title, t };

    // Only redraw when something visible changed
    const sig = JSON.stringify([title, dark, t.up, expected, rebootId, upd?.state, upd?.attributes?.in_progress,
      upd?.attributes?.latest_version, web, toggle,
      ports.map((p) => [p.id, p.st?.state, p.st?.attributes?.port_name, p.st?.attributes?.learned_macs, p.st?.attributes?.sfp])]);
    if (sig === this._sig) return;
    this._sig = sig;

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const col = COLORS[dark ? "dark" : "light"];
    let up = 0, below = 0;
    const tiles = ports.map((p) => {
      const state = p.st?.state;
      let cls = p.st?.attributes?.sfp ? "port sfp" : "port", label, color = "";
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
      // Slower than expected, or not connected at all
      const want = expected[p.num];
      let warn = "";
      if (want && state !== "disabled" && !((MBIT[state] || 0) >= want)) {
        below++;
        cls += " warn";
        warn = t.want(speedLabel(want), label);
      }
      const a = p.st?.attributes || {};
      const tip = [`Port ${p.num}`, a.port_name, a.sfp_module, a.learned_macs != null ? `${t.learned}: ${a.learned_macs}` : "", warn,
        toggle && !a.sfp ? t.hold : ""]
        .filter(Boolean)
        .join(" · ");
      return `<div class="${cls}" style="${color ? `--pc:${color}` : ""}" data-id="${esc(p.id)}" data-num="${p.num}" title="${esc(tip)}" role="button" tabindex="0">
        ${warn ? `<span class="wb">!</span>` : ""}<span class="pn">${p.num}</span><span class="jack"></span><span class="ps">${esc(label)}</span></div>`;
    });

    const acts = [
      updateOn
        ? `<button class="act upd" data-act="update" title="${esc(t.update_t(upd.attributes?.latest_version || ""))}"><ha-icon icon="mdi:package-up"></ha-icon>${esc(upd.attributes?.in_progress ? t.updating : t.update)}</button>`
        : "",
      rebootId ? `<button class="act" data-act="reboot" title="${esc(t.reboot)}" aria-label="${esc(t.reboot)}"><ha-icon icon="mdi:restart"></ha-icon></button>` : "",
      web ? `<a class="act" href="${esc(web)}" target="_blank" rel="noopener" title="${esc(t.web)}" aria-label="${esc(t.web)}"><ha-icon icon="mdi:open-in-new"></ha-icon></a>` : "",
    ].join("");
    const actsHtml = acts ? `<span class="acts">${acts}</span>` : "";

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 14px; }
        .head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 8px; margin-bottom: 8px; }
        .title { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .count { font-size: 12px; color: var(--secondary-text-color); }
        .strip { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 4px; }
        .port {
          width: 44px; border: 2px solid var(--divider-color); border-radius: 7px; padding: 3px 0 2px;
          text-align: center; cursor: pointer; background: var(--secondary-background-color);
          color: var(--primary-text-color); box-sizing: border-box; outline: none; position: relative;
        }
        .port:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
        .pn { font-weight: 650; font-size: 12px; display: block; }
        .ps { font-size: 9px; color: var(--secondary-text-color); display: block; line-height: 1.2; }
        .port.sfp { width: 50px; }
        /* Port symbols as on the switch: RJ45 jack with latch, SFP cage */
        .jack {
          display: block; width: 21px; height: 12px; margin: 4px auto 2px; border-radius: 2px; position: relative;
          border: 2px solid var(--secondary-text-color); border-top-width: 8px; opacity: .55; box-sizing: content-box;
        }
        .jack:before {
          content: ""; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
          width: 6px; height: 5px; margin-bottom: 7px; border-radius: 1px 1px 0 0; background-color: var(--secondary-text-color);
        }
        .sfp .jack { width: 24px; height: 16px; margin: 0 auto 2px; border-top-width: 5px; }
        .sfp .jack:before {
          width: 10px; margin-bottom: 2px; border-radius: 0 0 1px 1px; background-color: var(--secondary-background-color);
        }
        .port.up { border-color: var(--pc); background: color-mix(in srgb, var(--pc) 12%, var(--secondary-background-color)); }
        .port.up .jack { border-color: var(--pc); opacity: 1; }
        .port.up .jack:before { background-color: var(--pc); }
        .port.up.sfp .jack:before { background-color: color-mix(in srgb, var(--pc) 12%, var(--secondary-background-color)); }
        .port.up .ps { color: var(--pc); font-weight: 600; }
        .port.dis { opacity: .45; border-style: dashed; }
        .port.warn { border-color: var(--error-color, #db4437); opacity: 1; border-style: solid; }
        .port.warn .ps { color: var(--error-color, #db4437); font-weight: 600; }
        .wb {
          position: absolute; top: -7px; right: -7px; width: 15px; height: 15px; border-radius: 50%;
          background: var(--error-color, #db4437); color: #fff; font-size: 11px; font-weight: 700; line-height: 15px;
        }
        /* Long press to turn a port on or off: the tile fills up while held */
        /* touch-action none: otherwise Android takes a held finger for the start
           of a scroll and cancels the press */
        .strip.toggle .port { user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; touch-action: none; }
        .port.holding::after {
          content: ""; position: absolute; inset: 0; border-radius: 5px; background: var(--primary-color);
          opacity: .3; transform-origin: bottom; animation: hold ${HOLD_MS}ms linear forwards; pointer-events: none;
        }
        @keyframes hold { from { transform: scaleY(0); } to { transform: scaleY(1); } }
        .bad { font-size: 12px; color: var(--error-color, #db4437); font-weight: 600; }
        .acts { margin-left: auto; display: flex; gap: 2px; align-items: center; align-self: center; }
        .act {
          display: inline-flex; align-items: center; gap: 4px; height: 30px; min-width: 30px; padding: 0 6px;
          border: 0; border-radius: 15px; background: none; color: var(--secondary-text-color);
          cursor: pointer; font: inherit; font-size: 12px; text-decoration: none; box-sizing: border-box; justify-content: center;
        }
        .act:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }
        .act:focus-visible { outline: 2px solid var(--primary-color); }
        .act ha-icon { --mdc-icon-size: 20px; }
        .act.upd { color: var(--primary-color); font-weight: 600; background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
        .none { color: var(--secondary-text-color); font-size: 14px; }
      </style>
      <ha-card>
        ${title || ports.length ? `<div class="head"><span class="title">${esc(title)}</span>${ports.length ? `<span class="count">${up} / ${ports.length} ${esc(t.up)}</span>` : ""}${below ? `<span class="bad">⚠ ${esc(t.below(below))}</span>` : ""}${actsHtml}</div>` : ""}
        ${ports.length ? `<div class="strip${toggle ? " toggle" : ""}">${tiles.join("")}</div>` : `<div class="none">${esc(t.none)}</div>`}
      </ha-card>`;

    const more = (entityId) =>
      this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
    this.shadowRoot.querySelector('[data-act="update"]')?.addEventListener("click", () => more(updateId));
    this.shadowRoot.querySelector('[data-act="reboot"]')?.addEventListener("click", () => {
      askUser(t.reboot_q(title), t, t.do_reboot, () => this._hass.callService("button", "press", { entity_id: rebootId }));
    });

    this.shadowRoot.querySelectorAll(".port").forEach((el) => {
      const open = () =>
        this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: el.dataset.id } }));
      let timer = null, held = false;
      const cancel = () => {
        clearTimeout(timer);
        timer = null;
        el.classList.remove("holding");
      };
      el.addEventListener("click", () => {
        // The click that ends a long press does not open the details
        if (held) held = false;
        else open();
      });
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
      if (!toggle) return;
      el.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0 && ev.pointerType === "mouse") return;
        held = false;
        el.classList.add("holding");
        timer = setTimeout(() => {
          cancel();
          held = true;
          this._askToggle(Number(el.dataset.num), el.classList.contains("sfp"), el.classList.contains("dis"));
        }, HOLD_MS);
      });
      for (const ev of ["pointerup", "pointerleave", "pointercancel"]) el.addEventListener(ev, cancel);
      el.addEventListener("contextmenu", (ev) => ev.preventDefault());
    });
  }

  // After a long press: ask, then turn the port off or on through its switch entity
  _askToggle(num, sfp, off) {
    const { switches, title, t } = this._toggle;
    if (sfp) {
      askUser(t.no_sfp, t);
      return;
    }
    const entityId = switches[num];
    if (!entityId) {
      askUser(t.no_switch(num, title), t);
      return;
    }
    const st = this._hass.states[entityId]?.state;
    const isOn = st === "on" || (st !== "off" && !off);
    askUser(isOn ? t.off_q(num, title) : t.on_q(num, title), t, isOn ? t.do_off : t.do_on,
      () => this._hass.callService("switch", isOn ? "turn_off" : "turn_on", { entity_id: entityId }));
  }
}

// A question of the card's own, instead of window.confirm(): the Home Assistant
// app on Android does not show browser dialogs. It sits on document.body, so a
// redraw of the card does not take it away. Without `action` it only informs.
// Buttons only react to a press that starts after the dialog opened, so the
// finger still down from the long press cannot answer it on release.
function askUser(message, t, action, run) {
  document.getElementById(`${CARD}-ask`)?.remove();
  const host = document.createElement("div");
  host.id = `${CARD}-ask`;
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      .bg { position: fixed; inset: 0; z-index: 9999; background: rgba(0, 0, 0, .45);
        display: flex; align-items: center; justify-content: center; padding: 16px; }
      .box { background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
        border-radius: 12px; padding: 20px 20px 12px; max-width: 380px; width: 100%;
        box-shadow: 0 8px 28px rgba(0, 0, 0, .35); font-family: var(--paper-font-body1_-_font-family, sans-serif); }
      .msg { white-space: pre-line; font-size: 15px; line-height: 1.45; }
      .btns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
      button { font: inherit; font-size: 14px; font-weight: 500; border: 0; border-radius: 18px; padding: 9px 16px;
        cursor: pointer; background: none; color: var(--primary-color, #03a9f4); }
      button.pri { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
    </style>
    <div class="bg"><div class="box" role="dialog" aria-modal="true">
      <div class="msg"></div>
      <div class="btns">
        ${action ? `<button class="no">${esc(t.cancel)}</button><button class="yes pri">${esc(action)}</button>`
          : `<button class="no pri">${esc(t.ok)}</button>`}
      </div>
    </div></div>`;
  root.querySelector(".msg").textContent = message;
  let armed = false;
  root.addEventListener("pointerdown", () => { armed = true; });
  const close = () => {
    host.remove();
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (ev) => {
    if (ev.key === "Escape") close();
  };
  document.addEventListener("keydown", onKey);
  root.querySelector(".no").addEventListener("click", () => {
    if (armed) close();
  });
  root.querySelector(".yes")?.addEventListener("click", () => {
    if (!armed) return;
    close();
    run();
  });
  document.body.appendChild(host);
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
        const { expected_text, ...value } = ev.detail.value;
        if (expected_text !== undefined) this._typed = expected_text;
        const config = { ...this._config, ...value };
        if (!config.title) delete config.title;
        // Actions are on by default: only store the ones turned off
        for (const k of ["show_reboot", "show_update", "show_web"]) if (config[k] !== false) delete config[k];
        // Turning ports on and off is off by default: only store it when on
        if (config.port_toggle !== true) delete config.port_toggle;
        if (expected_text !== undefined) {
          const exp = parseExpected(expected_text);
          const keys = Object.keys(exp);
          if (keys.length) config.expected = Object.fromEntries(keys.map((k) => [k, speedLabel(exp[k])]));
          else delete config.expected;
        }
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
      { name: "expected_text", selector: { text: {} } },
      { name: "show_reboot", selector: { boolean: {} } },
      { name: "show_update", selector: { boolean: {} } },
      { name: "show_web", selector: { boolean: {} } },
      { name: "port_toggle", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (s) => (
      {
        device: t.device, title: t.title, expected_text: t.expected, show_reboot: t.show_reboot, show_update: t.show_update,
        show_web: t.show_web, port_toggle: t.port_toggle,
      }
    )[s.name];
    // Keep what is being typed; the stored config only holds the parsed ports
    if (this._typed === undefined || expectedText(this._typed) !== expectedText(this._config.expected)) {
      this._typed = expectedText(this._config.expected);
    }
    this._form.data = {
      show_reboot: true, show_update: true, show_web: true, port_toggle: false, ...this._config, expected_text: this._typed,
    };
  }
}

// Register the card. Some other cards swap the custom element registry for a
// polyfill while the dashboard loads; a definition made in that moment is
// lost. So check again for a few seconds and define once more if needed (with
// a fresh subclass, as a constructor may only be registered once).
function register() {
  try {
    if (!customElements.get(CARD)) customElements.define(CARD, class extends GenericRealtekSwitchCard {});
    if (!customElements.get(`${CARD}-editor`)) {
      customElements.define(`${CARD}-editor`, class extends GenericRealtekSwitchCardEditor {});
    }
  } catch (err) {
    console.warn(`${CARD}: registration failed, retrying`, err);
  }
}

register();
for (const ms of [50, 250, 1000, 2500, 5000, 10000]) setTimeout(register, ms);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Generic Realtek Switch",
    description: (navigator.language || "").startsWith("de")
      ? "Port-Leiste eines Switches: Geschwindigkeit pro Port, Klick für Details."
      : "Port strip of a switch: link speed per port, click for details.",
    preview: true,
  });
}
