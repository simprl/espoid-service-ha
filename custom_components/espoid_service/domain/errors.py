"""Stable application errors shared by rules, services and host adapters."""


class DeviceError(Exception):
    """Expose error codes, never upstream URLs or exception text."""

    def __init__(self, code: str, esp_error: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.esp_error = esp_error
