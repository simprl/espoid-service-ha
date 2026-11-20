"""Firmware composition identity and explicit composition-change admission."""
import hashlib
import json
from .device_resource_policy import validate_resource_data
from .errors import DeviceError


def validate_variant(value):
    try: validate_resource_data('firmware_variant', value)
    except DeviceError: raise DeviceError('invalid_firmware') from None
    features = value['features']
    if features != sorted(set(features)) or ('ble_equipment' in features and
        ('ble_protocol_engine' not in features or not value['platform'].endswith('-ble'))):
        raise DeviceError('invalid_firmware')
    definition = {key: item for key, item in value.items() if key != 'id'}
    raw = json.dumps(definition, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    if hashlib.sha256(raw).hexdigest() != value['id']:
        raise DeviceError('invalid_firmware')
    return value


def require_variant(current, target, allow_change=False):
    if type(allow_change) is not bool:
        raise DeviceError('invalid_request')
    target_id = validate_variant(target)['id'] if target is not None else None
    if not current or not target_id or current != target_id:
        if not allow_change:
            raise DeviceError('firmware_variant_change_required')
