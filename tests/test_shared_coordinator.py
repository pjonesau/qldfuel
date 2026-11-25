"""Tests for the shared, ref-counted coordinator in __init__.py and coordinator.py.

The coordinator class is replaced with a small fake so these exercise the
sharing, failure and release logic without a running Home Assistant.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from qldfuel import _async_get_shared_coordinator, _async_release_shared_coordinator
from qldfuel.const import DOMAIN
from qldfuel.coordinator import QldFuelDataCoordinator
from qldfuel.qldfuel_api import ApiAuthError, ApiError


class _FakeCoordinator:
    instances: list["_FakeCoordinator"] = []
    next_error: Exception | None = None

    def __init__(self, hass, api, update_interval_minutes):
        self.ref_count = 0
        self.entry_intervals = {}
        self.update_interval = timedelta(minutes=update_interval_minutes)
        self.refreshes = 0
        self.shut_down = False
        self.last_update_success = True
        self.last_exception = None
        _FakeCoordinator.instances.append(self)

    async def async_refresh(self):
        self.refreshes += 1
        if _FakeCoordinator.next_error is not None:
            self.last_update_success = False
            self.last_exception = _FakeCoordinator.next_error

    async def async_register_shutdown(self):
        pass

    async def async_shutdown(self):
        self.shut_down = True


@pytest.fixture
def fake_coordinator():
    _FakeCoordinator.instances = []
    _FakeCoordinator.next_error = None
    with patch("qldfuel.QldFuelDataCoordinator", _FakeCoordinator), patch(
        "qldfuel.QldFuelAPI", MagicMock()
    ):
        yield _FakeCoordinator


def _hass():
    return SimpleNamespace(data={DOMAIN: {}})


async def test_entries_share_one_coordinator_at_the_fastest_interval(fake_coordinator):
    hass = _hass()
    first = await _async_get_shared_coordinator(hass, "key", "entry_a", 10)
    second = await _async_get_shared_coordinator(hass, "key", "entry_b", 2)

    assert first is second
    assert first.refreshes == 1
    assert first.ref_count == 2
    assert first.update_interval == timedelta(minutes=2)


async def test_release_keeps_coordinator_running_for_remaining_entries(fake_coordinator):
    hass = _hass()
    coordinator = await _async_get_shared_coordinator(hass, "key", "entry_a", 10)
    await _async_get_shared_coordinator(hass, "key", "entry_b", 2)

    # Unloading the entry that created the coordinator must not stop it.
    await _async_release_shared_coordinator(hass, "key", "entry_a")
    assert not coordinator.shut_down
    assert coordinator.update_interval == timedelta(minutes=2)

    await _async_release_shared_coordinator(hass, "key", "entry_b")
    assert coordinator.shut_down
    assert "key" not in hass.data[DOMAIN]["_shared_coordinators"]


async def test_failed_first_refresh_is_not_shared(fake_coordinator):
    hass = _hass()
    fake_coordinator.next_error = UpdateFailed("down")

    with pytest.raises(ConfigEntryNotReady):
        await _async_get_shared_coordinator(hass, "key", "entry_a", 5)

    assert "key" not in hass.data[DOMAIN]["_shared_coordinators"]
    assert fake_coordinator.instances[0].shut_down

    fake_coordinator.next_error = None
    coordinator = await _async_get_shared_coordinator(hass, "key", "entry_a", 5)
    assert coordinator is fake_coordinator.instances[1]


async def test_rejected_key_on_first_refresh_raises_auth_failed(fake_coordinator):
    hass = _hass()
    error = UpdateFailed("rejected")
    error.__cause__ = ApiAuthError("401")
    fake_coordinator.next_error = error

    with pytest.raises(ConfigEntryAuthFailed):
        await _async_get_shared_coordinator(hass, "key", "entry_a", 5)


# --- QldFuelDataCoordinator itself ---


def _real_coordinator(hass, api):
    return QldFuelDataCoordinator(hass, api, 5)


def test_coordinator_is_not_bound_to_a_config_entry():
    coordinator = _real_coordinator(MagicMock(), MagicMock())
    assert coordinator.config_entry is None


async def test_rejected_key_starts_one_reauth_and_fails_the_update():
    hass = MagicMock()
    hass.async_add_executor_job.side_effect = ApiAuthError("401")
    entries = {"entry_a": MagicMock(), "entry_b": MagicMock()}
    hass.config_entries.async_get_entry.side_effect = entries.get
    coordinator = _real_coordinator(hass, MagicMock())
    coordinator.entry_intervals = {"entry_a": 5, "entry_b": 5}

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    entries["entry_a"].async_start_reauth.assert_called_once_with(hass)
    entries["entry_b"].async_start_reauth.assert_not_called()


async def test_connection_error_does_not_start_reauth():
    hass = MagicMock()
    hass.async_add_executor_job.side_effect = ApiError("timeout")
    coordinator = _real_coordinator(hass, MagicMock())
    coordinator.entry_intervals = {"entry_a": 5}

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    hass.config_entries.async_get_entry.assert_not_called()
