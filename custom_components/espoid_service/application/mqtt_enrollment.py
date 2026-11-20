"""One-use operator offers backed by local ESP administrator proof."""
from __future__ import annotations
import secrets
import time
from ..const import MAX_NODES
from ..domain.errors import DeviceError
from ..domain.mqtt_enrollment_policy import ENROLLMENT_TTL, mqtt_target, enrollment_certificate

class MqttEnrollment:
    def __init__(self, connections, bindings, *, now=time.monotonic):
        self.connections, self.bindings, self.now = connections, bindings, now
        self.offers = {}

    def create(self, identifier, owner, *, reset=False):
        row = self.connections.snapshot(identifier)["data"]
        if row["kind"] != "mqtt" or not row["actions"].get("rebind" if reset else "enroll") or not owner:
            raise DeviceError("service_unsupported")
        candidate = mqtt_target(row)
        record = self.bindings.for_node(candidate["node_id"])
        if type(reset) is not bool or (reset and record is None):
            raise DeviceError("invalid_request")
        if record and record.get("transport") == "mqtt" and record["topic"] != candidate["topic"]:
            raise DeviceError("binding_identity_mismatch")
        now = self.now()
        self.offers = {key: value for key, value in self.offers.items() if value["expires"] > now}
        if len(self.offers) >= MAX_NODES and identifier not in self.offers:
            raise DeviceError("too_many_nodes")
        existing = self.offers.get(identifier)
        if existing:
            if existing["owner"] != owner:
                raise DeviceError("operation_busy")
            if existing["candidate"] != candidate:
                raise DeviceError("binding_identity_mismatch")
            if existing["reset"] == reset:
                return {"id": identifier}
            # A fresh, explicit reset choice revokes this operator's unused offer.
            self.offers.pop(identifier)
        staged = record.get('replacement') if record else None
        evidence = staged or record
        self.offers[identifier] = {
            "reset": reset,
            "owner": owner, "expires": now + ENROLLMENT_TTL, "candidate": candidate,
            "id": identifier, "offer_id": secrets.token_hex(16), "service_id": self.bindings.service_id,
            "node_id": candidate["node_id"], "origin": candidate["admin_url"],
            "nonce": evidence["enrollment"] if evidence and "enrollment" in evidence else secrets.token_hex(32),
            "certificate": evidence["certificate"] if evidence and (staged or not reset) else None}
        return {"id": identifier}

    def snapshot(self, identifier, owner):
        offer = self._offer(identifier, owner)
        return {key: offer[key] for key in ("id", "offer_id", "service_id", "node_id", "origin",
                                            "nonce")}

    async def enroll(self, identifier, owner, value, request_id):
        offer = self._offer(identifier, owner)
        if set(value) != {"offer_id", "certificate"} or value["offer_id"] != offer["offer_id"]:
            raise DeviceError("invalid_request")
        certificate = enrollment_certificate(value["certificate"])
        if offer["certificate"] is not None and certificate != offer["certificate"]:
            raise DeviceError("binding_identity_mismatch")
        # Consume before admitting work. A failure requires an explicit new
        # offer; matching private pending state then supports deliberate retry.
        self.offers.pop(identifier)
        return await self.connections.execute(identifier, "enroll",
            {"certificate": certificate, "nonce": offer["nonce"], "reset": offer["reset"]}, request_id)

    def _offer(self, identifier, owner):
        offer = self.offers.get(identifier)
        if not offer or offer["owner"] != owner or self.now() >= offer["expires"]:
            raise DeviceError("enrollment_expired")
        return offer
