# ESPOID Service

Local Home Assistant maintenance for modular ESP nodes. Version 0.2.2 uses one
site entry and physical-node subentries. Requires HA Core 2026.3.4 or newer and
firmware supporting service API 1 (factory node identity and passive status).
The initial rollout has five nodes; the registry admits up to 200.

## Installation and upgrade

In HACS, add `https://github.com/simprl/espoid-service-ha` as a custom repository
of type **Integration**, download release **0.2.2**, then restart Home Assistant
and refresh the browser. For manual installation, copy the complete
`custom_components/espoid_service` directory, including `frontend` and
`translations`, into your HA configuration directory.

Before moving from 0.1.x, save a Home Assistant backup and preserve
`www/firmware/espoid_service`. First upgrade each old ESP through its existing
working Wi-Fi/USB update path to compatible firmware exposing service API 1.
Verify `/api/service/identity` and its factory node identity. Then remove the
old **ESPOID Service** entries, install 0.2.2, restart HA, and add the integration
once under **Settings → Devices & services**. Add the verified nodes from its
sidebar panel. Keep the existing MQTT and Zigbee2MQTT integrations in place.

This initial 0.1.x transition requires re-adding the pilot nodes once. Compatible
updates of the new site/subentry format preserve their IDs. Integration upgrades
do not update ESP firmware. To revert to 0.1.x, restore both its component and
matching configuration backup; the old version cannot load the new format.

## Fleet maintenance

Add ESPOID Service once. Configure the HA LAN origin reachable by nodes, optional
Z2M base topics and permitted search networks. Add verified HTTP nodes or connect
selected discovered nodes from the panel. Z2M import is optional; plain Wi-Fi/MQTT
compositions have the same stable identity. IP changes never create a new node.

While a node is reachable in Wi-Fi, use **Configure remote updates** once. This
sets its stable node-specific manifest URL and the site's local-only announcement
webhook. Import an immutable manifest and raw app image into the shared library.
Primary Zigbee composition update: Z2M command starts Wi-Fi URL OTA. No firmware
bytes are carried over Zigbee. Direct HA-to-ESP upload is the fallback. Non-Zigbee
nodes can use HTTP URL OTA or upload. No command is retried automatically.

Passive status does not confirm pending OTA. Explicit confirmation is available
for the expected artifact; firmware's existing unattended health policy still
applies. Transfer acceptance is not runtime confirmation. History survives HA
restart and retains uncertain outcomes for manual reconciliation.

Removing a service entry does not reset the ESP or remove its Z2M pairing.

Build: `npm run ha:build`. Package: `npm run ha:package`.
Tests: `npm run test:ha`, `npm run test:ha:ui`, `npm test` and stable firmware builds.
Artifacts are versioned under `dist/espoid-service/<version>/`; legacy surviving
`dist/home-assistant/` assets are untouched. The MIT licence applies only to this
HA integration and distribution, not to the ESP firmware.

Customer installation/restart, physical OTA and public release require their
explicit target/scope. A synthetic fixture is not hardware qualification.
