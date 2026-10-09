# ESPOID Service

Home Assistant integration for maintaining an ESPOID ESP32-C6 IO node from
HA itself. The browser only talks to HA; HA accesses the device's existing
temporary Wi-Fi HTTP API. No internet, external Python installation or CDN is
needed at runtime. Normal AC control remains in Zigbee2MQTT.

Version `0.1.2` adds explicit HA-local IP search. Discovery checks use local
fixtures, not native/customer HA qualification. The existing firmware and its
Wi-Fi service timers are unchanged; no ESP reflash is needed for this feature.

## Installation with HACS

Create and download a Home Assistant backup before installing. HACS installation
requires GitHub access from HA; an existing HACS installation alone does not
prove that downloads are reachable.

1. Open HACS, then its menu and **Custom repositories**.
2. Add `https://github.com/simprl/espoid-service-ha` with type **Integration**.
3. Find **ESPOID Service** and download release `0.1.2`, not the development branch.
4. Restart Home Assistant during an agreed maintenance window. Automations are
   unavailable while HA restarts. Do not update HA or other integrations as part
   of this installation.
5. Add **ESPOID Service** under **Settings > Devices & services > Add integration**.

For the first device, check status, explicitly extend Wi-Fi, read its profile and
download diagnostics, then return it to Zigbee. Do not start with firmware OTA
or profile changes. Downloading through HACS does not qualify the customer
network, real AC or firmware composition.

## Installation without HACS or internet

Copy the complete `custom_components/espoid_service` folder into your HA
configuration directory's `custom_components` folder using your file manager.
Keep the `frontend` and `translations` subfolders. Do not nest the domain folder
twice. Restart Home Assistant, then add **ESPOID Service** under
**Settings > Devices & services > Add integration**. No YAML edits are required.

Register each device with its local IPv4 HTTP address. Connection checking is
optional: leave it off if the device is currently in Zigbee mode. Change the
address through integration options when DHCP changes. The old firmware does
not expose its MAC through HTTP: config entries have stable generated IDs,
not IP-based IDs, and cannot automatically verify physical device identity.
Use DHCP reservations and check the board/profile before destructive actions.

The `0.1.2` panel also provides **Find IP** in the device bar. Request Wi-Fi from
Zigbee2MQTT, open search, confirm the private IPv4 subnet and start. The suggested
/24 is not a verified mask. HA checks the old IP and nearby addresses first
(+1, -1, +2, -2), with up to 12 concurrent requests and a 40-second deadline.
Only port 80 and the read-only `/api/device-config` route are probed. Results
appear progressively and can be stopped; even one candidate needs explicit
confirmation. Identical profiles do not identify a physical board: identify it
independently, or put only the intended board in Wi-Fi at a time.

Selection rereads the profile and updates the same HA entry's address and
remembered CIDR. ID/name, MQTT topic and library are preserved. Discovery sends
no ESP write, Wi-Fi hold, reboot or OTA. Selected-device polling/commands pause
while its search panel is open. Closing resumes normal polling, which can
confirm pending OTA through the existing status route; discovery never calls it.

The optional Zigbee2MQTT command topic is the complete device `/set` topic,
including the installation's prefix. The optional **Wi-Fi via Zigbee2MQTT**
button uses the existing HA MQTT integration and sends a non-retained
`reload_and_then: switch_to_wifi` command. No broker credentials are stored here.
Command acceptance is not proof of Zigbee delivery or a completed reboot.

The admin-only sidebar panel provides status, explicit Wi-Fi hold, Wi-Fi/Zigbee
restart, raw profile read/validate/save with readback verification, diagnostic
download, and a local firmware library. Opening/polling the panel never extends
Wi-Fi automatically. Each explicit hold adds the firmware's 30-minute extension;
the firmware cap is four hours, and reboot/power loss clears the RAM-only lease.

## Local firmware delivery

Import an existing Wi-Fi OTA `index.json` and its matching raw application
`.bin` together. This is not a factory/merged image or a Zigbee OTA file.
The import checks family, version, SHA-256, size, ESP32-C6 chip ID and the app
descriptor. It does not prove firmware compatibility, authenticity or real-AC
qualification; only import artifacts from a trusted build/release.

Images and rewritten relative manifests are stored immutably by hash below
`www/firmware/espoid_service`, outside the installed integration. HA serves
them without authentication at `/local/firmware/espoid_service/...` so the
existing ESP OTA client can download them. Never put credentials, profiles or
UART logs in `www`. Include the firmware directory in site backups.

Set the **Home Assistant LAN URL** in device options to an IPv4 HTTP origin
reachable **from the ESP**, including port 8123 when applicable. This is not
the laptop's VPN IP. Both HA -> ESP and ESP -> HA must be permitted. On a new
installation without a `www` folder, restart HA after the first import so its
standard `/local` file route is registered.

Select a firmware and explicitly confirm installation. The integration checks
the locally served manifest, saves only `ota_url` through the legacy form API,
verifies readback, and issues `/ota/install` once. It never retries writes or
follows device redirects. Monitor actual OTA state/running version, not the
accepted response. HA's publication check does not prove ESP -> HA access.
The firmware's rollback-enabled bootloader must already have been installed
with a full USB flash; this integration cannot update it via app-only OTA.

## Updating the integration

Keep a backup of the old component folder. Replace it completely with the new
folder to remove obsolete files, restart HA and reload the browser. Device
entries/options and the separate firmware library are preserved. The HACS ZIP
contains component contents at its root, so extract it **into**
`custom_components/espoid_service`, not the entire configuration directory.
There is no integration self-updater or arbitrary filesystem/proxy endpoint.

## Scope and translations

The public ESPOID Service `0.1.1` pilot's scoped native HA
2026.4.4 checks covered that release and its preceding name, with a
synthetic HTTP fixture. Panel/config/options, service API, local publication
and restart persistence passed. Neither result is
a production release or real-AC qualification. Firmware checkpoints and service timers
are unchanged. The generic gateway/BLE API is not used. No raw UART electrical
test or arbitrary AC command is exposed; never run bench challenges on a real AC.
Raw UART diagnostic downloads can contain installation/protocol information;
review them before sharing. All maintenance API routes require an HA admin.

Native HA forms ship complete `translations/en.json`, `uk.json`, `ru.json`.
The panel bundles typed dictionaries and follows the HA user's language, with
English fallback. As in the existing iLazyHome HA projects, `ru` intentionally
uses the Ukrainian translation. Packaging generates that file from `uk` and
checks keys, placeholders and actual flow labels. Browser tests cover localized
labels, errors and operations. No dependence on runtime `strings.json`.

The public distribution repository is generated from the source project;
the release workflow and validation limits are documented in
`docs/HA_SERVICE_INTEGRATION.md` in the source repository.

The HACS distribution repository is `simprl/espoid-service-ha`. The firmware
website will be `espoid.com`, but offline-site firmware stays
in the HA-local library. No cloud connection is required or configured.

## License

This HA integration and its distribution repository are licensed under MIT;
see `LICENSE`. The component ZIP includes the same notice. This license does
not apply to the separate ESP firmware source or firmware images.
