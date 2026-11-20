"""Stable binding target keys shared by private storage and public resources."""

def binding_key(record):
    return "mqtt:" + record["node_id"] if record.get("transport") == "mqtt" else record["prefix"] + ":" + record["ieee"]
