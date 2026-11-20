"""Availability hints only; TLS identity/credentials still authorize every RPC."""
from __future__ import annotations
import re
from .domain.errors import DeviceError

MODELS = frozenset(('espoid', 'esp-c6-io-node', 'esp-c6-contact-inputs', 'esp-c6-contact-i'))


def service_control_supported(candidate, record, announcements):
    # Routing hints select a protocol before authentication. They never permit
    # fallback after failure or replace the saved binding key/certificate.
    observed = announcements.get(record['node_id'], {})
    versions = (observed.get('firmware_id'), candidate.get('firmware_version'),
                (record.get('status') or {}).get('firmware_version'))
    return any(isinstance(version,str) and re.fullmatch(r'0x[0-9a-fA-F]{8}',version)
               and int(version,16) >= 0x000100da for version in versions)


def service_support(candidate):
    if candidate.get('transport')=='mqtt':
        return {'binding':True,'network':True,'machine':True,'resources':True,'reason':None}
    version = candidate.get('firmware_version')
    number = int(version, 16) if isinstance(version, str) and re.fullmatch(r'0x[0-9a-fA-F]{8}', version) else None
    bits = candidate.get('service_capabilities')
    reason = None
    if number is not None and number < 0x00010049:
        reason = 'service_legacy'
    elif candidate.get('service_converter') is not True:
        reason = 'service_converter_required'
    elif number is not None and 0x00010049 <= number <= 0x00010050:
        # These sealed development images predate the capability attribute.
        bits = 1 if number < 0x0001004e else 3
    elif type(bits) is not int or not 0 <= bits <= 255:
        reason = 'service_capabilities_unknown'
    return {'binding': reason is None and bool(bits & 1),
            'network': reason is None and (bits & 3) == 3,
            'machine': reason is None and (bits & 5) == 5,
            'resources': reason is None and (bits & 13) == 13,
            'reason': reason or (None if bits & 1 else 'service_unsupported')}


def require_service_feature(candidate, feature):
    support = service_support(candidate)
    if support.get(feature) is not True:
        raise DeviceError(support['reason'] or 'service_unsupported')
