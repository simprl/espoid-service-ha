"""Resource HTTP views with one explicit HA registration entry point."""

from .connections import ConnectionsView, ConnectionView
from .devices import DevicesView
from .firmware import FirmwareView, FirmwareImportView
from .maintenance import MachineExchangeView, MachineTransferView
from .network import NetworkProbeView
from .profiles import ProfileView
from .profile_files import ProfileFileView
from .resources import DeviceResourceView
from .search import SearchView
from .settings import SettingsView
from .history import HistoryView
from .mqtt_setup import MqttSetupView


def register_views(hass):
    for view in (
        DevicesView,
        HistoryView,
        MqttSetupView,
        SettingsView,
        ConnectionsView,
        ConnectionView,
        NetworkProbeView,
        SearchView,
        ProfileView,
        ProfileFileView,
        DeviceResourceView,
        FirmwareView,
        FirmwareImportView,
        MachineExchangeView,
        MachineTransferView,
    ):
        hass.http.register_view(view(hass))
