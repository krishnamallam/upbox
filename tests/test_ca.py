"""Tests for upbox/ca.py.

CI must never touch the real system trust store or the real keychain. Tests
that exercise install/uninstall against the system either monkeypatch
``subprocess.run`` or are gated on a tool being available (e.g. ``certutil``
for the real NSS round-trip).
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509

from upbox import ca


@pytest.fixture
def tmp_ca_dir(tmp_path: Path) -> Path:
    """A fresh CA directory under pytest's tmp_path. No leakage between tests."""
    return tmp_path / "ca"


@pytest.fixture
def tmp_nss_db(tmp_path: Path) -> str:
    """A fresh, empty NSS db path in certutil's ``sql:`` form."""
    db_dir = tmp_path / "nssdb"
    db_dir.mkdir()
    return f"sql:{db_dir}"


def test_generate_ca_writes_cert_and_key(tmp_ca_dir: Path) -> None:
    cert, key = ca.generate_ca(tmp_ca_dir)

    assert cert.exists() and key.exists()


def test_generate_ca_produces_parseable_certificate(tmp_ca_dir: Path) -> None:
    cert, _ = ca.generate_ca(tmp_ca_dir)
    parsed = x509.load_pem_x509_certificate(cert.read_bytes())

    assert ca.CA_COMMON_NAME in parsed.subject.rfc4514_string()


def test_generate_ca_marks_certificate_as_ca(tmp_ca_dir: Path) -> None:
    cert, _ = ca.generate_ca(tmp_ca_dir)
    parsed = x509.load_pem_x509_certificate(cert.read_bytes())
    bc = parsed.extensions.get_extension_for_class(x509.BasicConstraints).value

    assert bc.ca is True


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits don't apply on Windows (NTFS uses ACLs)",
)
def test_generate_ca_key_has_mode_0600(tmp_ca_dir: Path) -> None:
    _, key = ca.generate_ca(tmp_ca_dir)
    mode = stat.S_IMODE(key.stat().st_mode)

    assert mode == 0o600


def test_generate_ca_is_idempotent_without_force(tmp_ca_dir: Path) -> None:
    cert_first, _ = ca.generate_ca(tmp_ca_dir)
    first_bytes = cert_first.read_bytes()
    ca.generate_ca(tmp_ca_dir)

    assert cert_first.read_bytes() == first_bytes


def test_generate_ca_force_overwrites(tmp_ca_dir: Path) -> None:
    cert, _ = ca.generate_ca(tmp_ca_dir)
    first_bytes = cert.read_bytes()
    ca.generate_ca(tmp_ca_dir, force=True)

    assert cert.read_bytes() != first_bytes


def test_get_status_reports_cert_missing_before_generate(tmp_ca_dir: Path) -> None:
    status = ca.get_status(tmp_ca_dir)

    assert status.cert_exists is False


def test_get_status_reports_cert_exists_after_generate(tmp_ca_dir: Path) -> None:
    ca.generate_ca(tmp_ca_dir)
    status = ca.get_status(tmp_ca_dir)

    assert status.cert_exists is True


def test_electron_app_hint_includes_cert_path(tmp_ca_dir: Path) -> None:
    hint = ca.electron_app_hint(tmp_ca_dir)

    assert str(ca.cert_path(tmp_ca_dir)) in hint


def test_electron_app_hint_recommends_upbox_run(tmp_ca_dir: Path) -> None:
    hint = ca.electron_app_hint(tmp_ca_dir)

    assert "upbox run" in hint


def test_electron_app_hint_on_windows_does_not_use_bash_assignment(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: previous hint printed `NODE_EXTRA_CA_CERTS=<path> <app>`,
    # which is bash inline-env syntax. On Windows PowerShell that does
    # nothing and silently fails to route the tool.
    monkeypatch.setattr(ca.platform, "system", lambda: "Windows")
    hint = ca.electron_app_hint(tmp_ca_dir)

    assert "NODE_EXTRA_CA_CERTS=" not in hint


def test_install_linux_nss_returns_false_when_certutil_missing(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ca.shutil, "which", lambda _name: None)
    cert, _ = ca.generate_ca(tmp_ca_dir)

    assert ca.install_linux_nss(cert) is False


def test_uninstall_linux_nss_returns_false_when_certutil_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ca.shutil, "which", lambda _name: None)

    assert ca.uninstall_linux_nss() is False


def test_install_macos_invokes_security_add_trusted_cert(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    cert, _ = ca.generate_ca(tmp_ca_dir)
    ca.install_macos(cert)

    assert captured[0][:5] == ["sudo", "security", "add-trusted-cert", "-d", "-r"]


def test_install_linux_system_invokes_update_ca_certificates(
    tmp_ca_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    cert, _ = ca.generate_ca(tmp_ca_dir)
    ca.install_linux_system(cert)

    assert captured[-1] == ["sudo", "update-ca-certificates"]


def test_uninstall_macos_invokes_security_delete_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    ca.uninstall_macos()

    assert captured[0][:4] == ["sudo", "security", "delete-certificate", "-c"]


@pytest.mark.skipif(
    shutil.which("certutil") is None or sys.platform == "win32",
    reason="NSS certutil not available (Windows ships its own unrelated certutil.exe)",
)
def test_install_then_uninstall_linux_nss_round_trips(tmp_ca_dir: Path, tmp_nss_db: str) -> None:
    cert, _ = ca.generate_ca(tmp_ca_dir)
    ca.install_linux_nss(cert, nss_db=tmp_nss_db)
    installed = ca.is_in_linux_nss(nss_db=tmp_nss_db)
    ca.uninstall_linux_nss(nss_db=tmp_nss_db)
    removed = not ca.is_in_linux_nss(nss_db=tmp_nss_db)

    assert installed and removed


def test_write_mitmproxy_bundle_contains_both_key_and_cert(
    tmp_ca_dir: Path, tmp_path: Path
) -> None:
    ca.generate_ca(tmp_ca_dir)
    confdir = tmp_path / "mitm"

    ca.write_mitmproxy_bundle(tmp_ca_dir, confdir)
    bundle = (confdir / ca.MITM_CA_FILENAME).read_bytes()
    cert_alone = (tmp_ca_dir / ca.CA_CERT_FILENAME).read_bytes()
    key_alone = (tmp_ca_dir / ca.CA_KEY_FILENAME).read_bytes()

    assert key_alone in bundle and cert_alone in bundle


def test_write_mitmproxy_bundle_raises_when_ca_missing(tmp_ca_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ca.write_mitmproxy_bundle(tmp_ca_dir, tmp_path / "mitm")
