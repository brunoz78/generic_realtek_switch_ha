# HORACO Managed Switch

Native Home-Assistant-Integration für HORACO HC-SWTGW218AS, HC-SWTGW215AS, ZX-SWTGW215AS,
keepLink KP9000 / KP-9000-9XHML-X und kompatible OEM-Managed-Switches.

**Keine zusätzliche App und kein Zwischendienst nötig** — die Integration spricht direkt mit der CGI-Schnittstelle des Switches oder, bei der quelloffenen Firmware RTLPlayground, mit deren JSON-Schnittstelle (wird automatisch erkannt).

### Was du bekommst

- Ein Gerät pro Switch, mehrere Switches parallel
- Ein Sensor pro Port mit Verbindung und Geschwindigkeit, optional Duplex, Flusskontrolle, Paket- und Fehlerzähler
- Taste für den Neustart des Switches
- Mit RTLPlayground zusätzlich die Chip-Temperatur
- Vollständig lokal, keine Cloud

### Einrichtung

IP-Adresse des Switches, HTTP-Port (Standard 80) und Zugangsdaten (Werkseinstellung meist admin / admin) eingeben. Für jeden Switch die Integration einmal hinzufügen.
