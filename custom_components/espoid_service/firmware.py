"""Operator-imported raw app images, separate from installed integration code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import os
import uuid
import threading

from .domain.errors import DeviceError
from .domain.address_policy import validate_local_origin as local_url
from .const import APP_MAX_BYTES, DOMAIN, FAMILY
from .domain.firmware_variant_policy import validate_variant

HASH = re.compile(r"[0-9a-f]{64}\Z")
VERSION_HEX = re.compile(r"0x[0-9a-fA-F]{8}\Z")


def validate_image(manifest: dict, image: bytes) -> dict:
    try:
        artifact = manifest["artifact"]
        digest = hashlib.sha256(image).hexdigest()
        if (manifest["family"] != FAMILY or not VERSION_HEX.fullmatch(manifest["version"])
                or type(artifact["size"]) is not int or artifact["size"] != len(image)
                or artifact["sha256"].lower() != digest
                or not 288 <= len(image) <= APP_MAX_BYTES
                or image[0] != 0xE9 or struct.unpack_from("<H", image, 12)[0] != 13
                or struct.unpack_from("<I", image, 32)[0] != 0xABCD5432):
            raise DeviceError("invalid_firmware")
    except (KeyError, TypeError, AttributeError, struct.error) as err:
        raise DeviceError("invalid_firmware") from err
    variant = image_variant(image)
    if manifest.get("variant") != variant:
        raise DeviceError("invalid_firmware")
    if variant is not None and (image[48:59] != (manifest["version"].lower() + "\0").encode()
        or image[80:97] != b"esp32_c6_io_node\0"):
        raise DeviceError("invalid_firmware")
    return {"family": FAMILY, "version": manifest["version"].lower(), "variant": variant,
            "channel": str(manifest.get("channel", "operator"))[:40],
            "artifact": {"file": "firmware.bin", "size": len(image), "sha256": digest}}


def image_variant(image):
    offset = 288
    if image[offset:offset+16] != b'ESPOID-VARIANT1\0':
        return None
    if len(image) < offset + 512 or struct.unpack_from('<I', image, 28)[0] < 768:
        raise DeviceError('invalid_firmware')
    raw = image[offset+16:offset+512]
    end = raw.find(b'\0')
    if end < 0 or any(raw[end:]):
        raise DeviceError('invalid_firmware')
    try:
        def unique(pairs):
            output = {}
            for key, value in pairs:
                if key in output: raise ValueError()
                output[key] = value
            return output
        return validate_variant(json.loads(raw[:end], object_pairs_hook=unique))
    except (ValueError, UnicodeError):
        raise DeviceError('invalid_firmware') from None


class FirmwareLibrary:
    def __init__(self, config_dir: str) -> None:
        self.config_dir = Path(config_dir).resolve()
        self.root = self.config_dir / "www" / "firmware" / DOMAIN
        self._import_lock = threading.Lock()

    def _safe(self) -> None:
        for path in [self.root, *self.root.parents]:
            if path == self.config_dir:
                break
            if path.is_symlink():
                raise DeviceError("invalid_firmware")
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, digest: str) -> dict:
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise DeviceError("invalid_firmware")
        self._safe()
        folder = self.root / digest
        if folder.is_symlink() or any((folder / name).is_symlink() for name in ("index.json", "firmware.bin")):
            raise DeviceError("invalid_firmware")
        try:
            if (folder / "index.json").stat().st_size > 4096 or (folder / "firmware.bin").stat().st_size > APP_MAX_BYTES:
                raise DeviceError("invalid_firmware")
            manifest = json.loads((folder / "index.json").read_text(encoding="utf-8"))
            validated = validate_image(manifest, (folder / "firmware.bin").read_bytes())
            if validated["artifact"]["sha256"] != digest:
                raise DeviceError("invalid_firmware")
            return {**validated, "id": digest}
        except (OSError, ValueError) as err:
            raise DeviceError("invalid_firmware") from err

    def list(self) -> list[dict]:
        self._safe()
        result = []
        for folder in sorted(self.root.iterdir()):
            if len(result) >= 256:
                break
            if HASH.fullmatch(folder.name):
                try:
                    result.append(self.get(folder.name))
                except DeviceError:
                    continue
        return result

    def publish_node(self, node_id: str, digest: str, base: str) -> dict:
        from .model import node_id as validate_node
        validate_node(node_id)
        base = local_url(base)
        manifest = self.get(digest)
        folder = self.root / "nodes" / node_id
        if (self.root / "nodes").is_symlink() or folder.is_symlink():
            raise DeviceError("storage_failed")
        folder.mkdir(parents=True, exist_ok=True)
        clean = {k:v for k,v in manifest.items() if k != "id"}
        clean["artifact"] = {**clean["artifact"], "url": f"{base}/local/firmware/{DOMAIN}/{digest}/firmware.bin"}
        temporary = folder / ("index-" + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(clean,indent=2)+"\n",encoding="utf-8")
            os.replace(temporary, folder / "index.json")
        finally:
            temporary.unlink(missing_ok=True)
        return clean

    def import_image(self, manifest: dict, image: bytes) -> dict:
        with self._import_lock:
            return self._import_image(manifest, image)

    def _import_image(self, manifest: dict, image: bytes) -> dict:
        normalized = validate_image(manifest, image)
        self._safe()
        digest = normalized["artifact"]["sha256"]
        target = self.root / digest
        if target.exists():
            saved = self.get(digest)
            if saved["version"] != normalized["version"]:
                raise DeviceError("invalid_firmware")
            return saved
        stage = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
        try:
            (stage / "firmware.bin").write_bytes(image)
            (stage / "index.json").write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return {**normalized, "id": digest}
