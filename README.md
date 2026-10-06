# Generic Realtek Switch — Home-Assistant-Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/brunoz78/generic_realtek_switch_ha)](https://github.com/brunoz78/generic_realtek_switch_ha/releases)
[![Validate](https://github.com/brunoz78/generic_realtek_switch_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/brunoz78/generic_realtek_switch_ha/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

Überwache Managed Switches mit Realtek-Chip direkt in Home Assistant — **ohne zusätzliche App, ohne Docker, ohne Zwischendienst**. Gemeint sind Switches mit der verbreiteten Realtek-Weboberfläche, wie sie viele günstige Marken verwenden (z. B. HORACO, keepLink, Lianguo, Mokerlink), sowie alle Switches mit der Ersatz-Firmware [RTLPlayground](#rtlplayground). Ob ein Switch passt, entscheidet seine Weboberfläche, nicht die Marke — siehe [Unterstützte Geräte](#unterstützte-geräte).

Die Integration meldet sich an der Weboberfläche des Switches an und liest Geräte-Info, Port-Status und Zähler direkt von dessen Seiten aus. Sie erkennt dabei zwei Seitenaufbauten der Firmware: einen, bei dem die Port-Daten auf der Info-Seite stehen, und einen, bei dem sie auf der Port-Seite stehen (z. B. keepLink KP-9000-9XHML-X und HORACO ZX-SWTGW215AS). Pro Switch entsteht ein Gerät; mehrere Switches lassen sich parallel einbinden. Die Namen der Entitäten erscheinen in der Sprache von Home Assistant (Deutsch oder Englisch).

Läuft auf dem Switch die quelloffene Firmware [RTLPlayground](https://github.com/logicog/RTLPlayground), erkennt die Integration das automatisch und liest stattdessen deren JSON-Schnittstelle — siehe [RTLPlayground](#rtlplayground).

---

## Unterstützte Geräte

### Mit der Original-Firmware

| Modell | Ports | SFP+ | Status |
|--------|-------|------|--------|
| keepLink KP-9000-9XHML-X (HW V3.1, FW V100.9.9.1.7) | 8 × 2.5GbE | 1 × 10G | ✅ Getestet |
| HORACO ZX-SWTGW218AS (HW V1.1, FW V1.9.1) | 8 × 2.5GbE | 1 × 10G | ✅ Getestet |
| HORACO ZX-SWTGW215AS (HW V1.1, FW V1.9) | 5 × 2.5GbE | 1 × 10G | ✅ Getestet |
| keepLink KP9000-9XH-X | 8 × GbE | 1 × 10G | ☑️ Laut Originalprojekt bestätigt |
| HORACO HC-SWTGW218AS | 8 × GbE | 2 × 10G | ☑️ Laut Originalprojekt bestätigt |
| HORACO HC-SWTGW215AS | 5 × GbE | — | ☑️ Laut Originalprojekt bestätigt |

Andere Switches mit Realtek RTL8372/RTL8373 und derselben Weboberfläche (Anmeldung mit Benutzername und Passwort auf Port 80, Seiten `info.cgi` und `port.cgi`) funktionieren sehr wahrscheinlich auch.

### Mit der Ersatz-Firmware [RTLPlayground](#rtlplayground)

Ab Version 2.1.0 der Integration.

| Modell | Ports | SFP+ | Status |
|--------|-------|------|--------|
| keepLink KP-9000-9XHML-X (HW V3.1) | 8 × 2.5GbE | 1 × 10G | ✅ Getestet |
| keepLink KP-9000-9XHML-X (HW V3.2) | 8 × 2.5GbE | 1 × 10G | ✅ Getestet |
| HORACO ZX-SWTGW218AS (HW V1.1) | 8 × 2.5GbE | 1 × 10G | ✅ Getestet |
| HORACO ZX-SWTGW215AS (HW V1.1) | 5 × 2.5GbE | 1 × 10G | ✅ Getestet |

Getestet mit RTLPlayground `v0.1.0-0e9c997`. Die Weboberfläche ist auf allen Geräten gleich; jeder Switch aus der [Geräteliste von RTLPlayground](https://github.com/logicog/RTLPlayground/blob/main/doc/supported_devices.md) sollte deshalb funktionieren.

**Legende:** ✅ selbst getestet · ☑️ von anderen bestätigt oder sehr ähnlich

**Kompatibles Gerät gefunden?** Eröffne ein [Issue](https://github.com/brunoz78/generic_realtek_switch_ha/issues/new), damit es in die Tabelle aufgenommen wird.

---

## Funktionen

- 🔌 **Port-Überwachung** — ein Sensor pro Port mit Verbindung und Geschwindigkeit (z. B. `Getrennt`, `1000M`, `2500M`), optional Duplex, Flusskontrolle, Paket- und Fehlerzähler
- 🔄 **Neustart-Taste** — Switch per Knopfdruck aus jedem Dashboard oder jeder Automation neu starten
- ⚡ **Direkte Abfrage im LAN** — vollständig lokal, keine Cloud, kein Proxy
- 🔧 **Einstellbares Abfrageintervall** — 10 bis 300 Sekunden (Standard 30 s)

---

## Installation

### Über HACS (empfohlen)

1. HACS → Integrationen → ⋮ → **Benutzerdefinierte Repositories**
2. URL: `https://github.com/brunoz78/generic_realtek_switch_ha` · Typ: **Integration**
3. **Generic Realtek Switch** installieren und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Generic Realtek Switch**

### Manuell

1. Die Datei `generic_realtek_switch.zip` des neuesten [Releases](https://github.com/brunoz78/generic_realtek_switch_ha/releases/latest) herunterladen
2. Entpacken und den Ordner `generic_realtek_switch/` nach `<config>/custom_components/` kopieren
3. Home Assistant neu starten und die Integration über die Oberfläche hinzufügen

---

## Einrichtung

| Feld | Standard | Hinweis |
|------|----------|---------|
| IP-Adresse des Switches | — | z. B. `192.168.1.100` |
| HTTP-Port | `80` | Nur ändern, wenn die Weboberfläche auf einem anderen Port läuft |
| Benutzername | `admin` | Werkseinstellung der meisten Modelle; bei [RTLPlayground](#rtlplayground) einfach `admin` stehen lassen |
| Passwort | `admin` | Werkseinstellung der meisten Modelle; bei RTLPlayground ab Werk `1234` |

Für jeden Switch die Integration einmal hinzufügen. Nach der Einrichtung kannst du über **Konfigurieren** auf der Integrationskarte das Abfrageintervall anpassen (10–300 s).

---

## Entitäten

Pro Switch gibt es **ein Gerät** mit dem Namen `Switch <IP-Adresse>`, z. B. `Switch 192.168.1.100`. Alle Entitäten — auch die der einzelnen Ports — hängen direkt an diesem Gerät.

### Switch

| Entität | Typ | Beschreibung |
|---------|-----|--------------|
| Firmware | Sensor | Firmware-Version |
| MAC-Adresse | Sensor | MAC-Adresse des Switches |
| Aktive Ports | Sensor | Anzahl verbundener Ports |
| Ports gesamt | Sensor | Anzahl physischer Ports |
| Neustart | Taste | Startet den Switch neu |
| Betriebszeit | Sensor | z. B. `3d 14h 22m` — **nur** wenn die Firmware die Laufzeit meldet (KP-9000-9XHML-X und ZX-SWTGW215AS tun das nicht) |
| Temperatur | Sensor | Chip-Temperatur in °C — **nur** mit RTLPlayground |

### Pro Port *(N = 1 … Anzahl Ports)*

| Entität | Typ | Standard | Beschreibung |
|---------|-----|----------|--------------|
| Port N | Sensor | aktiv | Verbindung und Geschwindigkeit in einem: `Getrennt` · `Deaktiviert` · `10M` · `100M` · `1000M` · `2500M` · `5000M` · `10G`. Enthält alle Port-Werte als Attribute. |
| Port N Duplex | Sensor | deaktiviert | `Vollduplex` oder `Halbduplex` |
| Port N Flusskontrolle | Sensor | deaktiviert | `Ein` oder `Aus` |
| Port N Gesendete Pakete | Sensor | deaktiviert | Gesendete Pakete (fortlaufend) |
| Port N Empfangene Pakete | Sensor | deaktiviert | Empfangene Pakete (fortlaufend) |
| Port N Sendefehler | Sensor | deaktiviert | Fehlerhaft gesendete Pakete (fortlaufend) — steigende Werte deuten auf Kabel- oder Steckerprobleme hin |
| Port N Empfangsfehler | Sensor | deaktiviert | Fehlerhaft empfangene Pakete (fortlaufend) |
| Port N Gesendet / Empfangen | Sensor | deaktiviert | Bytes (fortlaufend) — **nur** wenn der Switch Byte-Zähler liefert (KP-9000-9XHML-X und ZX-SWTGW215AS tun das nicht) |

**Getrennt** heisst: Der Port ist eingeschaltet, aber es ist kein Gerät verbunden (kein Kabel oder Gegenstelle aus). **Deaktiviert** heisst: Der Port wurde in der Weboberfläche des Switches bewusst abgeschaltet.

Deaktivierte Entitäten lassen sich bei Bedarf unter **Einstellungen → Geräte & Dienste → Entitäten** einschalten.

Schlägt das Lesen der Statistikseite einmal fehl, zeigen die Paket- und Fehlerzähler kurz „Unbekannt“ statt `0`. So hält Home Assistant einen Aussetzer nicht fälschlich für einen Zählerreset, der die Langzeitstatistik verfälschen würde.

Die Entitäts-IDs sind unabhängig von der Sprache immer englisch und folgen dem Muster `sensor.switch_192_168_1_100_port_3`, `sensor.switch_192_168_1_100_port_3_duplex`, `…_flow_control`, `…_tx_packets`, `…_rx_errors` usw. In Automationen lauten die Zustände des Port-Sensors `disconnected`, `disabled`, `10m`, `100m`, `1000m`, `2500m`, `5000m` und `10g`.

---

## Beispiel-Automationen

### Benachrichtigung, wenn ein Port ausfällt

```yaml
alias: "Switch-Port 3 getrennt"
triggers:
  - trigger: state
    entity_id: sensor.switch_192_168_1_100_port_3
    to: "disconnected"
    for: "00:00:30"
actions:
  - action: notify.mobile_app
    data:
      title: "⚠️ Netzwerk-Warnung"
      message: "Switch-Port 3 ist nicht mehr verbunden"
```

### Wöchentlicher Neustart

```yaml
alias: "Switch-Neustart Sonntag 3 Uhr"
triggers:
  - trigger: time
    at: "03:00:00"
conditions:
  - condition: time
    weekday: [sun]
actions:
  - action: button.press
    target:
      entity_id: button.switch_192_168_1_100_reboot
```

---

## Funktionsweise

Bei jeder Abfrage (alle N Sekunden):

1. **Anmeldung** — `POST /login.cgi` mit Benutzername, Passwort und `MD5(Benutzername + Passwort)`; der Hash wird bei den folgenden Anfragen als Cookie mitgeschickt
2. `GET /info.cgi` → Modell, Firmware, MAC, Laufzeit; je nach Firmware zusätzlich Link und Geschwindigkeit pro Port
3. `GET /port.cgi?page=stats` → Paket- und Fehlerzähler pro Port
4. `GET /port.cgi` → Port aktiviert/deaktiviert; steht auf `/info.cgi` keine Porttabelle (z. B. KP-9000-9XHML-X, ZX-SWTGW215AS), kommen Link, Geschwindigkeit/Duplex und Flusskontrolle von hier

Die **Neustart**-Taste sendet `POST /reboot.cgi` mit `cmd=reboot`.

Jede Anfrage schickt den HTTP-Header `Referer` mit. Neuere Firmware (z. B. V100.9.9.1.7 auf Hardware V3.1) liefert ohne diesen Header eine leere Seite — deshalb bleibt eine direkt in die Adresszeile eingegebene URL wie `http://<ip>/info.cgi` dort weiss. Ältere Firmware (z. B. V1.9 auf Hardware V1.1) prüft das nicht.

Zwischen den einzelnen Anfragen liegt eine Pause von 0,4 s, damit der Mikrocontroller des Switches nicht überlastet wird. Bricht der Switch eine Verbindung ohne Antwort ab (kommt bei manchen Firmware-Versionen gelegentlich vor), wird die Anfrage bis zu dreimal wiederholt.

---

## RTLPlayground

[RTLPlayground](https://github.com/logicog/RTLPlayground) ist eine quelloffene Ersatz-Firmware für Switches mit Realtek RTL8372/RTL8373. Die Integration erkennt sie beim Einrichten und bei jedem Start von Home Assistant an der Anmeldeseite. Wird ein bereits eingebundener Switch umgeflasht, stellt sie selbst um, sobald der Eintrag neu geladen wird (Einstellungen → Geräte & Dienste → Generic Realtek Switch → ⋮ → **Neu laden**) oder Home Assistant neu startet — vorausgesetzt, IP-Adresse und Passwort sind gleich geblieben; sonst den Switch in Home Assistant löschen und neu hinzufügen. Duplex- und Flusskontroll-Entitäten der Original-Firmware verschwinden dabei.

**Einrichtung:** wie oben. RTLPlayground kennt keinen Benutzernamen: Das Feld kann auf `admin` stehen bleiben, es wird ignoriert. Das Passwort ist ab Werk `1234`.

**Was anders ist:**

| | Original-Firmware | RTLPlayground |
|---|---|---|
| Port N, Gesendete/Empfangene Pakete, Sende-/Empfangsfehler | ✅ | ✅ |
| Port N Duplex, Port N Flusskontrolle | ✅ | — (meldet die Firmware nicht) |
| Temperatur des Switch-Chips | — | ✅ |
| Port-Name und SFP-Modul | — | als Attribute `port_name` und `sfp_module` am Sensor „Port N“ |
| Firmware | z. B. `V1.9.1` | z. B. `RTLPlayground v0.1.0-f0aea3d` |

Ein SFP-Steckplatz ohne Modul erscheint als `Getrennt`, nicht als `Deaktiviert`.

**Eine Sitzung zugleich:** Die Firmware kennt nur eine angemeldete Sitzung. Meldet man sich im Browser an, verliert Home Assistant seine Sitzung. Die Integration erkennt das und **pausiert die Abfrage dann für 5 Minuten** (die Entitäten sind so lange „Nicht verfügbar“), damit die Weboberfläche benutzbar bleibt; danach meldet sie sich wieder an — und meldet damit den Browser ab.

**Abfrage:** `POST /login` mit dem Passwort → Sitzungs-Cookie; danach `GET /information.json` (Modell, MAC, Firmware, Temperatur) und `GET /status.json` (Link, Geschwindigkeit, Paket- und Fehlerzähler pro Port). Die Neustart-Taste ruft `GET /reset` auf.

---

## Mitwirken

Ablauf: Fork → Branch → Pull Request → alle CI-Prüfungen grün (HACS, hassfest, Parser-Tests) → Merge.

Die Parser-Tests laufen ohne Switch und ohne Home Assistant gegen echte Seiten der getesteten Modelle (`tests/fixtures/`):

```bash
pip install -r requirements_test.txt
python -m pytest tests
```

Wer ein neues Modell ergänzt, legt am besten dessen `info.cgi`, `port.cgi` und `port.cgi?page=stats` (MAC und IP anonymisiert) als neuen Ordner unter `tests/fixtures/` ab.

**Kompatibles Gerät gefunden?** Eröffne ein [Issue](https://github.com/brunoz78/generic_realtek_switch_ha/issues/new) mit Modell, Firmware-Version und Port-Ausstattung, dann wird es in die Tabelle aufgenommen.

---

## Lizenz

MIT — siehe [LICENSE](LICENSE)

## Danksagung

Ursprünglich ein Fork von [gtrancillo/horaco_switch_ha](https://github.com/gtrancillo/horaco_switch_ha).

Wissen über die CGI-Endpunkte und den Abfrage-Ansatz stammt aus [byte4geek/switch-dashboard](https://github.com/byte4geek/switch-dashboard).
