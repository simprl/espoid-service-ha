"""Observe device status through the configured path and reconcile OTA evidence."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.errors import DeviceError
from ..domain.device_status_policy import status_read_error


class DeviceStatusService:
    def __init__(self, registry, maintenance, *, now: Callable[[], str]):
        self.registry = registry
        self.maintenance = maintenance
        self.now = now
        self.observed = None

    async def refresh(self, node):
        registry = self.registry
        machine = self.maintenance
        bindings = getattr(machine, 'bindings', None) if machine else None
        mqtt = bindings.mqtt_candidate(node.node_id) if bindings and hasattr(bindings, "mqtt_candidate") else None
        if mqtt or machine and machine.supports(node):
            try:
                candidate = bindings.sources.candidate(node.z2m) if bindings and not mqtt else None
                from ..service_support import service_support
                if mqtt:
                    snapshot = await bindings.mqtt_status(node.node_id)
                    if snapshot['error']: raise DeviceError(snapshot['error'])
                    result = snapshot['data']
                    machine.observe_boot(node.node_id, result['boot_id'])
                    node.status, node.reachable, node.checked_at = result, True, self.now()
                elif bindings and service_support(candidate).get('resources'):
                    async with machine.bindings.lock:
                        snapshot = await machine.bindings.resource_rpc(candidate, {'resource': 'status', 'action': 'item'})
                    if snapshot['error']: raise DeviceError(snapshot['error'])
                    result = snapshot['data']
                    machine.observe_boot(node.node_id, result['boot_id'])
                    node.status, node.reachable, node.checked_at = result, True, self.now()
                else:
                    result = await machine.refresh(node)
            except (DeviceError, TimeoutError, OSError) as error:
                # Keep the existing observation during an unresolved job; never
                # fall back to legacy HTTP for a bound machine device.
                node.reachable = False
                raise DeviceError(status_read_error(error)) from None
            await registry.save()
            if self.observed:
                await self.observed(node)
            return result
        raise DeviceError("service_unsupported")
