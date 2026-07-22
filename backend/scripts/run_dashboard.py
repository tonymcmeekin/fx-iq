"""Start the local Trade IQ backend and dashboard with readiness checks."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Protocol

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIRECTORY = REPOSITORY_ROOT / "backend"
FRONTEND_DIRECTORY = REPOSITORY_ROOT / "frontend"
BACKEND_PYTHON = BACKEND_DIRECTORY / ".venv" / "bin" / "python"
DASHBOARD_URL = "http://127.0.0.1:5173"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/ai/provider-readiness"


class DashboardLaunchError(RuntimeError):
    pass


class ProcessLike(Protocol):
    def poll(self) -> int | None: ...


def validate_requirements() -> str:
    if not BACKEND_PYTHON.is_file():
        raise DashboardLaunchError(
            "Backend setup is missing. Run 'make setup' from the project folder first."
        )
    npm = shutil.which("npm")
    if npm is None:
        raise DashboardLaunchError("Node.js/npm is missing and is required for the dashboard.")
    if not (FRONTEND_DIRECTORY / "node_modules").is_dir():
        raise DashboardLaunchError(
            "Dashboard packages are missing. Run 'cd frontend && npm install' once."
        )
    return npm


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def verify_ports_available() -> None:
    occupied = [str(port) for port in (8000, 5173) if port_in_use(port)]
    if occupied:
        raise DashboardLaunchError(
            "Dashboard port(s) already in use: "
            + ", ".join(occupied)
            + ". Stop the existing dashboard and try again."
        )


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError):
        return False


def wait_until_ready(
    processes: Mapping[str, ProcessLike],
    endpoints: Mapping[str, str],
    *,
    timeout_seconds: float = 20.0,
    probe: Callable[[str], bool] = http_ready,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for name, process in processes.items():
            if process.poll() is not None:
                raise DashboardLaunchError(f"{name} stopped during startup.")
        if all(probe(url) for url in endpoints.values()):
            return
        time.sleep(0.1)
    raise DashboardLaunchError("Dashboard startup timed out before health checks passed.")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def log_tail(log: IO[str], *, maximum_lines: int = 12) -> str:
    log.seek(0)
    return "".join(log.readlines()[-maximum_lines:]).strip()


def main() -> int:
    processes: dict[str, subprocess.Popen[str]] = {}
    with (
        tempfile.TemporaryFile(mode="w+t") as backend_log,
        tempfile.TemporaryFile(mode="w+t") as frontend_log,
    ):
        try:
            npm = validate_requirements()
            verify_ports_available()
            processes["Backend"] = subprocess.Popen(
                [
                    str(BACKEND_PYTHON),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=BACKEND_DIRECTORY,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            processes["Dashboard"] = subprocess.Popen(
                [
                    npm,
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5173",
                    "--strictPort",
                ],
                cwd=FRONTEND_DIRECTORY,
                stdout=frontend_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wait_until_ready(
                processes,
                {"Backend": BACKEND_HEALTH_URL, "Dashboard": DASHBOARD_URL},
            )
            print()
            print("TRADE IQ DASHBOARD IS READY")
            print(f"Open: {DASHBOARD_URL}")
            print("Local read-only mode. Press Control+C here to stop both services.")
            print()
            while all(process.poll() is None for process in processes.values()):
                time.sleep(0.5)
            raise DashboardLaunchError("A dashboard service stopped unexpectedly.")
        except KeyboardInterrupt:
            print("\nStopping Trade IQ dashboard...")
            return 0
        except DashboardLaunchError as error:
            print(f"\nDASHBOARD COULD NOT START: {error}")
            for name, log in (("Backend", backend_log), ("Dashboard", frontend_log)):
                tail = log_tail(log)
                if tail:
                    print(f"\n{name} details:\n{tail}")
            return 1
        finally:
            for process in processes.values():
                stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
