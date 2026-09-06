"""Test harness for the MyHOME cover platform.

Home Assistant and OWNd are heavy, version-sensitive dependencies that we do
not want to install just to exercise the pure time-based positioning logic in
``cover.py``. Instead we register lightweight stand-ins for every external and
sibling module in ``sys.modules`` *before* importing the real ``cover.py``.

This lets the tests drive the genuine ``handle_event`` /
``_extrapolate_position`` / periodic-timer code paths with:

* a controllable fake clock (``clock`` fixture) so elapsed-time maths are
  deterministic and no real ``sleep`` is needed;
* a recording fake for ``async_track_time_interval`` so tests can fire timer
  ticks by hand and assert the tracker is started/cancelled correctly;
* a fake gateway that records the OWN commands the entity would send.
"""

from __future__ import annotations

import enum
import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "myhome"


def _new_module(name: str, is_pkg: bool = False) -> types.ModuleType:
    module = types.ModuleType(name)
    if is_pkg:
        module.__path__ = []  # mark as a package so submodule imports resolve
    sys.modules[name] = module
    return module


# --------------------------------------------------------------------------- #
# Recording tracker used to stub homeassistant.helpers.event
# --------------------------------------------------------------------------- #
TRACKERS: list[dict] = []


def _install_stub_modules() -> None:
    # ---- homeassistant.components.cover ---------------------------------- #
    _new_module("homeassistant", is_pkg=True)
    _new_module("homeassistant.components", is_pkg=True)
    cover_ns = _new_module("homeassistant.components.cover")
    cover_ns.ATTR_POSITION = "position"
    cover_ns.DOMAIN = "cover"

    class CoverDeviceClass:
        SHUTTER = "shutter"

    class CoverEntityFeature(enum.IntFlag):
        OPEN = 1
        CLOSE = 2
        SET_POSITION = 4
        STOP = 8

    class CoverEntity:  # minimal Entity stand-in
        hass = None

    cover_ns.CoverDeviceClass = CoverDeviceClass
    cover_ns.CoverEntityFeature = CoverEntityFeature
    cover_ns.CoverEntity = CoverEntity

    # ---- homeassistant.const --------------------------------------------- #
    const_ns = _new_module("homeassistant.const")
    const_ns.CONF_NAME = "name"
    const_ns.CONF_MAC = "mac"
    const_ns.CONF_ENTITIES = "entities"

    # ---- homeassistant.core ---------------------------------------------- #
    core_ns = _new_module("homeassistant.core")

    def _callback(func):  # the @callback decorator is a passthrough
        return func

    core_ns.callback = _callback
    core_ns.CALLBACK_TYPE = object

    # ---- homeassistant.helpers.event ------------------------------------- #
    _new_module("homeassistant.helpers", is_pkg=True)
    event_ns = _new_module("homeassistant.helpers.event")

    def async_track_time_interval(hass, action, interval, *args, **kwargs):
        record = {"action": action, "interval": interval, "cancelled": False}
        TRACKERS.append(record)

        def _unsub():
            record["cancelled"] = True

        return _unsub

    event_ns.async_track_time_interval = async_track_time_interval

    # ---- OWNd.message ---------------------------------------------------- #
    _new_module("OWNd", is_pkg=True)
    msg_ns = _new_module("OWNd.message")

    class OWNAutomationEvent:  # only used for isinstance-free duck typing
        pass

    class OWNAutomationCommand:
        @staticmethod
        def status(where):
            return ("status", where)

        @staticmethod
        def raise_shutter(where):
            return ("raise", where)

        @staticmethod
        def lower_shutter(where):
            return ("lower", where)

        @staticmethod
        def stop_shutter(where):
            return ("stop", where)

        @staticmethod
        def set_shutter_level(where, level):
            return ("set", where, level)

    msg_ns.OWNAutomationEvent = OWNAutomationEvent
    msg_ns.OWNAutomationCommand = OWNAutomationCommand

    # ---- custom_components.myhome package + siblings ---------------------- #
    cc = _new_module("custom_components", is_pkg=True)
    cc.__path__ = [str(ROOT / "custom_components")]
    mh = _new_module("custom_components.myhome", is_pkg=True)
    mh.__path__ = [str(PKG_DIR)]

    # const.py only depends on the stdlib ``logging`` module -> load the real one.
    _load_real_module("custom_components.myhome.const", PKG_DIR / "const.py")

    # myhome_device.MyHOMEEntity: a minimal base that records HA state writes.
    device_ns = _new_module("custom_components.myhome.myhome_device")

    class MyHOMEEntity:
        def __init__(
            self,
            hass,
            name: str,
            platform: str,
            device_id: str,
            who: str,
            where: str,
            manufacturer: str,
            model: str,
            gateway,
        ):
            self.hass = hass
            self._hass = hass
            self._platform = platform
            self._who = who
            self._where = where
            self._device_id = device_id
            self._manufacturer = manufacturer
            self._model = model
            self._gateway_handler = gateway
            self._attr_name = None
            self._write_count = 0

        def async_write_ha_state(self):
            self._write_count += 1

        def async_schedule_update_ha_state(self, *args, **kwargs):
            self._write_count += 1

    device_ns.MyHOMEEntity = MyHOMEEntity

    # gateway.MyHOMEGatewayHandler is only referenced as a type annotation.
    gateway_ns = _new_module("custom_components.myhome.gateway")

    class MyHOMEGatewayHandler:
        pass

    gateway_ns.MyHOMEGatewayHandler = MyHOMEGatewayHandler


def _load_real_module(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Install stubs and import the real cover module exactly once, at collection time.
_install_stub_modules()
cover = _load_real_module("custom_components.myhome.cover", PKG_DIR / "cover.py")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
class FakeClock:
    """Controllable replacement for ``datetime`` inside cover.py."""

    def __init__(self, start: datetime):
        self._now = start

    # ``cover.py`` calls ``datetime.now()`` with no arguments.
    def now(self, tz=None):  # noqa: D401 - mimics datetime.now signature
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock(datetime(2026, 1, 1, 12, 0, 0))
    monkeypatch.setattr(cover, "datetime", fake)
    return fake


class FakeGateway:
    """Records the OWN commands an entity would send on the bus."""

    mac = "AA:BB:CC:DD:EE:FF"
    unique_id = "gateway-unique-id"
    log_id = "[GW]"

    def __init__(self):
        self.sent: list = []
        self.status_requests: list = []

    async def send(self, command):
        self.sent.append(command)

    async def send_status_request(self, command):
        self.status_requests.append(command)


class FakeEvent:
    """Stand-in for OWNd.message.OWNAutomationEvent."""

    def __init__(
        self,
        *,
        is_opening=None,
        is_closing=None,
        is_closed=None,
        current_position=None,
        human_readable_log="event",
    ):
        self.is_opening = is_opening
        self.is_closing = is_closing
        self.is_closed = is_closed
        self.current_position = current_position
        self.human_readable_log = human_readable_log


@pytest.fixture(autouse=True)
def _reset_trackers():
    TRACKERS.clear()
    yield
    TRACKERS.clear()


@pytest.fixture
def make_cover():
    """Factory building a non-advanced, time-based cover with a fake gateway."""

    def _factory(opening_time=10, closing_time=10, advanced=False):
        gateway = FakeGateway()
        entity = cover.MyHOMECover(
            hass={},
            name="Living Room Shade",
            entity_name="Shade",
            device_id="shade-1",
            who="2",
            where="10",
            interface=None,
            advanced=advanced,
            manufacturer="Test Mfr",
            model="Test Model",
            opening_time=opening_time,
            closing_time=closing_time,
            gateway=gateway,
        )
        return entity

    return _factory


@pytest.fixture
def trackers():
    return TRACKERS


# Convenience re-exports for tests
Event = FakeEvent
