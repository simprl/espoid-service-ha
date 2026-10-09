"""Operator-imported raw app images, separate from installed integration code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import threading

from .client import DeviceError
from .const import APP_MAX_BYTES, DOMAIN, FAMILY

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
    return {"family": FAMILY, "version": manifest["version"].lower(),
            "channel": str(manifest.get("channel", "operator"))[:40],
            "artifact": {"file": "firmware.bin", "size": len(image), "sha256": digest}}


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
