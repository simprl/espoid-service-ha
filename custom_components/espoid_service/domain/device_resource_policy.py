"""Transport-independent resource DTOs, identities and Wi-Fi proof fingerprints."""
from __future__ import annotations

import hashlib
import hmac
import json
from ..resource_contract import RESOURCE_PROTOCOL, RESOURCE_DEFINITIONS
from .errors import DeviceError
from .schema_policy import schema_matches


def resource_request(value):
    action = value.get('action') if isinstance(value, dict) else None
    schema = 'ResourceReadRequest' if action == 'item' else 'ResourceSaveRequest' if action == 'save' else 'ResourceCommandRequest'
    if not schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS[schema], value):
        raise DeviceError('invalid_request')
    raw = resource_bytes(value)
    if len(raw) > RESOURCE_PROTOCOL['MQTT_REQUEST_BYTES' if value.get('resource')=='mqtt' else 'REQUEST_BYTES']:
        raise DeviceError('invalid_request')
    if schema == 'ResourceCommandRequest' and (value['resource'], action) not in {
        ('system', 'restart'), ('system', 'hold_wifi'), ('system', 'retry_startup'),
        ('zigbee', 'reset_network'), ('zigbee', 'restart_zigbee'), ('service', 'check')
    }:
        raise DeviceError('invalid_request')
    if schema == 'ResourceCommandRequest' and set(value) != {'resource', 'action', 'request_id', 'boot_id', 'expected_mode'}:
        raise DeviceError('invalid_request')
    if schema == 'ResourceSaveRequest' and value['resource'] == 'wifi':
        data = value['data']
        ssid, password, mode = data['ssid'], data.get('password'), data['password_action']
        try:
            valid = 1 <= len(ssid.encode('utf-8')) <= 32 and '\0' not in ssid
            if mode == 'replace':
                valid = valid and isinstance(password, str) and '\0' not in password and (
                    8 <= len(password.encode('utf-8')) <= 63 or len(password) == 64 and all(c in '0123456789abcdefABCDEF' for c in password))
            else:
                valid = valid and 'password' not in data
        except UnicodeError:
            valid = False
        if not valid:
            raise DeviceError('invalid_request')
    return raw


def resource_response(value, request, node_id):
    if isinstance(value, dict) and 'data' not in value and value.get('error'):
        if not schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS['ResourceAcknowledgement'], value):
            raise DeviceError('invalid_response')
        if value['id'] != node_id:
            raise DeviceError('identity_mismatch')
        if len(resource_bytes(value)) > RESOURCE_PROTOCOL['RESPONSE_BYTES']:
            raise DeviceError('invalid_response')
        return value
    schema = 'ResourceSnapshot' if request['action'] == 'item' else 'ResourceAcknowledgement'
    if not schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS[schema], value) or value['id'] != node_id:
        raise DeviceError('identity_mismatch' if isinstance(value, dict) and value.get('id') != node_id else 'invalid_response')
    if schema == 'ResourceSnapshot':
        if value['entity'] != request['resource']:
            raise DeviceError('invalid_response')
        validate_resource_data(request['resource'], value['data'])
        if request['resource'] == 'status' and value['data']['node_id'] != node_id:
            raise DeviceError('identity_mismatch')
    if len(resource_bytes(value)) > RESOURCE_PROTOCOL['RESPONSE_BYTES']:
        raise DeviceError('invalid_response')
    return value


def validate_resource_data(entity, value):
    schema = {'status': 'StatusResourceData', 'wifi': 'WifiResourceData', 'zigbee': 'ZigbeeResourceData', 'mqtt': 'MqttResourceData',
              'service': 'ServiceResourceData', 'profile': 'ProfileResourceData', 'diagnostics': 'DiagnosticsResourceData', 'firmware_variant': 'FirmwareVariant'}[entity]
    if entity == 'status' and schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS['RuntimeStatusResourceData'], value):
        return
    if not schema_matches(RESOURCE_DEFINITIONS, RESOURCE_DEFINITIONS[schema], value):
        raise DeviceError('invalid_response')


def resource_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError):
        raise DeviceError('invalid_request') from None


def wifi_fingerprint(request, origin, key):
    data = request['data']
    parts = ('ESPOID-WIFI-1', request['expected_revision'], data['ssid'], data['password_action'], data.get('password', ''), origin)
    return hmac.new(key, b'\0'.join(part.encode('utf-8') for part in parts) + b'\0', hashlib.sha256).hexdigest()
