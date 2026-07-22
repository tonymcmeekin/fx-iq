"""Checks for the one-command local dashboard supervisor."""

import pytest

from scripts.run_dashboard import DashboardLaunchError, wait_until_ready


class FakeProcess:
    def __init__(self, return_code=None):
        self.return_code = return_code

    def poll(self):
        return self.return_code


def test_wait_until_ready_requires_every_local_service():
    probes = []

    def ready(url):
        probes.append(url)
        return True

    wait_until_ready(
        {"Backend": FakeProcess(), "Dashboard": FakeProcess()},
        {"Backend": "backend", "Dashboard": "dashboard"},
        timeout_seconds=0.1,
        probe=ready,
    )

    assert probes == ["backend", "dashboard"]


def test_wait_until_ready_fails_if_a_service_exits():
    with pytest.raises(DashboardLaunchError, match="Backend stopped"):
        wait_until_ready(
            {"Backend": FakeProcess(return_code=1)},
            {"Backend": "backend"},
            timeout_seconds=0.1,
            probe=lambda url: False,
        )
