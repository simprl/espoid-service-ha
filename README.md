# ESPOID Service

Local Home Assistant integration for managing ESP devices, reading configuration
and diagnostics, and installing firmware updates. Requires Home Assistant Core
**2026.3.4** or newer and firmware compatible with ESPOID Service 0.3.

## Install or update with HACS

Add this repository in HACS as a custom repository of type **Integration**.
Download ESPOID Service and restart Home Assistant. For a manual installation,
extract the release asset into `custom_components/espoid_service`.

### Zigbee Service mode in 0.3.2

In **Connections**, read the device mode, then enter Service mode or return
to normal operation directly over Zigbee. Use firmware and an ESPOID
converter that support mode switching (bench-tested on Haier firmware
`0x00010119` with the matching converter). Existing Service bindings carry
over. Firmware and the converter are updated separately.

### Upgrade from 0.2.2

1. Create a Home Assistant backup. Save the Zigbee2MQTT configuration if you use it.
2. Confirm that the ESP devices already run firmware compatible with Service 0.3.
   For the Haier migration from firmware `0x0001005e`, install the matching
   Zigbee2MQTT converter and update the ESPs through Service 0.2.2 first. Verify
   that they return to Zigbee and report climate data. The qualified migration
   image is `0x00010117`.
3. Update the existing integration to the latest release in HACS and restart Home Assistant.
   Keep the existing integration entry and device records.
4. Set the Home Assistant URL reachable from the ESP devices in Service settings.
   For a previously registered node, use **Connections → Bind** to authorize the
   new Service connection. Verify the node's status and configuration.

If a legacy OTA operation is still shown as unconfirmed, check the running
firmware on the ESP before resolving the operation in Service. An integration
update leaves ESP firmware and Zigbee network membership in place.

The MIT license applies to this Home Assistant integration.
