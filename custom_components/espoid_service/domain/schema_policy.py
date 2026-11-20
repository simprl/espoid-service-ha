"""Bounded generated DTO validation shared by resource and equipment adapters."""
import math


def schema_matches(definitions, schema, value):
    if '$ref' in schema:
        return schema_matches(definitions, definitions[schema['$ref'].split('/')[-1]], value)
    if 'oneOf' in schema:
        return sum(schema_matches(definitions, branch, value) for branch in schema['oneOf']) == 1
    if 'const' in schema:
        return type(value) is type(schema['const']) and value == schema['const']
    if 'enum' in schema and value not in schema['enum']:
        return False
    kind = schema.get('type')
    if kind == 'object':
        properties = schema.get('properties', {})
        additional = schema.get('additionalProperties')
        return isinstance(value, dict) and schema.get('minProperties', 0) <= len(value) <= schema.get('maxProperties', math.inf) and (
            'propertyNames' not in schema or all(schema_matches(definitions, schema['propertyNames'], key) for key in value)) and (
            set(schema.get('required', [])) <= value.keys()) and all(
                schema_matches(definitions, properties[key], item) if key in properties else
                schema_matches(definitions, additional, item) if isinstance(additional, dict) else additional is True
                for key, item in value.items())
    if kind == 'array':
        return isinstance(value, list) and schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf) and all(
            schema_matches(definitions, schema['items'], item) for item in value)
    if kind == 'null':
        return value is None
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'number':
        return type(value) in (float, int) and math.isfinite(value) and schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf) and ('exclusiveMinimum' not in schema or value > schema['exclusiveMinimum'])
    if kind == 'integer':
        return type(value) is int and schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf)
    if kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', math.inf):
            return False
        if 'pattern' in schema:
            import re
            if not re.fullmatch(schema['pattern'], value):
                return False
        return 'enum' not in schema or value in schema['enum']
    return False
