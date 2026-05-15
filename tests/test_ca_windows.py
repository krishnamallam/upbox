"""Windows-specific tests for upbox/ca.py.

CI on Windows runs these; CI on POSIX exercises them via monkeypatched
subprocess. The actual Windows trust store is never touched in tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from upbox import ca


@pytest.fixture
def tmp_ca_dir(tmp_path: Path) -> Path:
    return tmp_path / "ca"


def test_install_windows_invokes_certutil_addstore(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    cert, _ = ca.generate_ca(tmp_ca_dir)
    ca.install_windows(cert)

    assert captured[0][:5] == ["certutil", "-user", "-addstore", "-f", "Root"]


def test_uninstall_windows_invokes_certutil_delstore(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    ca.uninstall_windows()

    assert captured[0][:4] == ["certutil", "-user", "-delstore", "Root"]


def test_is_in_windows_trust_returns_false_when_certutil_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(ca.subprocess, "run", fake_run)

    assert ca.is_in_windows_trust() is False


def test_get_status_reports_none_for_windows_field_on_linux(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ca.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ca.shutil, "which", lambda _name: None)
    ca.generate_ca(tmp_ca_dir)

    status = ca.get_status(tmp_ca_dir)

    assert status.in_windows_trust is None
