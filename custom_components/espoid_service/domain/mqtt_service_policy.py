"""Operations enabled on the direct MQTT Service carrier in this stage."""

OPERATIONS = frozenset((
    "profile_read", "profile_validate", "profile_store", "profile_file",
    "diagnostics", "diagnostics_save", "ota", "ota_confirm", "reboot_wifi", "recovery_retry", "service_enter", "service_exit",
))


def control_supported(action):
    return action in ("reboot_wifi", "recovery_retry", "check", "resolve", "service_enter", "service_exit")



def resource_supported(request):
    return (request.get("resource"), request.get("action")) in {
        ("status", "item"), ("wifi", "item"), ("wifi", "save"),
        ("mqtt", "item"), ("mqtt", "save"),
    }
