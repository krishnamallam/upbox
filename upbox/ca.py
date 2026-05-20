"""Local Certificate Authority for upbox.

Generates a self-signed root CA, installs it to platform trust stores, and
reports trust status. Linux needs three layers because different apps read
different cert stores:

- System trust (``/usr/local/share/ca-certificates`` + ``update-ca-certificates``)
  covers ``curl``, ``wget``, and system Python's ``requests``.
- NSS (``~/.pki/nssdb`` via ``certutil``) covers Firefox, Chrome (sometimes),
  and any Electron app that uses NSS.
- ``NODE_EXTRA_CA_CERTS`` env var covers Node-based Electron apps that read
  Node's bundled cert list (Cursor, Claude desktop, VSCode).

macOS uses the System keychain via ``security add-trusted-cert``.

The CA cert and private key are stored under ``~/.upbox/ca/`` with the key at
mode 0600. mitmproxy will read the same cert + key on Day 3.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

DEFAULT_CA_DIR = Path.home() / ".upbox" / "ca"
CA_CERT_FILENAME = "upbox-ca.pem"
CA_KEY_FILENAME = "upbox-ca.key"
CA_COMMON_NAME = "upbox local CA"
CA_ORGANIZATION = "upbox"
CA_VALIDITY_DAYS = 365 * 10

LINUX_SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
LINUX_SYSTEM_CA_FILENAME = "upbox-ca.crt"
LINUX_SYSTEM_CA_SYMLINK = Path("/etc/ssl/certs/upbox-ca.pem")

DEFAULT_NSS_DB = f"sql:{Path.home() / '.pki' / 'nssdb'}"
NSS_NICKNAME = "upbox-ca"

MACOS_KEYCHAIN = "/Library/Keychains/System.keychain"

DEFAULT_MITM_CONFDIR = Path.home() / ".upbox" / "mitm"
MITM_CA_FILENAME = "mitmproxy-ca.pem"

WINDOWS_CERT_STORE = "Root"  # Trusted Root Certification Authorities


@dataclass(frozen=True)
class CAStatus:
    """Trust-status snapshot reported by ``upbox status``.

    Fields are ``None`` on platforms where the layer does not apply. For
    example ``in_macos_keychain`` is ``None`` on Linux.
    """

    cert_exists: bool
    cert_path: Path
    in_macos_keychain: bool | None
    in_linux_system_trust: bool | None
    in_linux_nss: bool | None
    nss_certutil_available: bool | None
    in_windows_trust: bool | None


def cert_path(ca_dir: Path = DEFAULT_CA_DIR) -> Path:
    return ca_dir / CA_CERT_FILENAME


def key_path(ca_dir: Path = DEFAULT_CA_DIR) -> Path:
    return ca_dir / CA_KEY_FILENAME


def generate_ca(ca_dir: Path = DEFAULT_CA_DIR, force: bool = False) -> tuple[Path, Path]:
    """Generate the upbox root CA and write it to ``ca_dir``.

    Returns ``(cert_path, key_path)``. If the cert already exists and
    ``force`` is False, this is a no-op and existing paths are returned.
    """
    cert = cert_path(ca_dir)
    key = key_path(ca_dir)

    if cert.exists() and key.exists() and not force:
        return cert, key

    ca_dir.mkdir(parents=True, exist_ok=True)
    ca_dir.chmod(0o700)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, CA_COMMON_NAME),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, CA_ORGANIZATION),
        ]
    )

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=CA_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
    )
    certificate = builder.sign(private_key, hashes.SHA256())

    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key.write_bytes(key_bytes)
    key.chmod(0o600)

    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    cert.write_bytes(cert_bytes)
    cert.chmod(0o644)

    return cert, key


def install_macos(cert: Path) -> None:
    """Install the CA to the macOS System keychain. Requires sudo prompt."""
    subprocess.run(
        [
            "sudo",
            "security",
            "add-trusted-cert",
            "-d",
            "-r",
            "trustRoot",
            "-k",
            MACOS_KEYCHAIN,
            str(cert),
        ],
        check=True,
    )


def uninstall_macos() -> None:
    """Remove the CA from the macOS System keychain. Requires sudo prompt."""
    subprocess.run(
        ["sudo", "security", "delete-certificate", "-c", CA_COMMON_NAME, MACOS_KEYCHAIN],
        check=True,
    )


def install_linux_system(cert: Path) -> None:
    """Install the CA to Linux system trust (``/usr/local/share/ca-certificates``).

    Covers ``curl``, ``wget``, and system Python. Requires sudo.
    """
    dest = LINUX_SYSTEM_CA_DIR / LINUX_SYSTEM_CA_FILENAME
    subprocess.run(["sudo", "cp", str(cert), str(dest)], check=True)
    subprocess.run(["sudo", "update-ca-certificates"], check=True)


def uninstall_linux_system() -> None:
    """Remove the CA from Linux system trust. Requires sudo."""
    dest = LINUX_SYSTEM_CA_DIR / LINUX_SYSTEM_CA_FILENAME
    subprocess.run(["sudo", "rm", "-f", str(dest)], check=True)
    subprocess.run(["sudo", "update-ca-certificates", "--fresh"], check=True)


def install_linux_nss(cert: Path, nss_db: str = DEFAULT_NSS_DB) -> bool:
    """Install the CA to the Linux NSS database.

    Returns ``True`` if installed, ``False`` if ``certutil`` is not on PATH
    (caller should print the install hint).
    """
    if not shutil.which("certutil"):
        return False

    nssdb_path = _nss_db_path(nss_db)
    nssdb_path.mkdir(parents=True, exist_ok=True)

    # Initialize an empty NSS db if it doesn't have one yet.
    if not any(nssdb_path.iterdir()):
        subprocess.run(
            ["certutil", "-d", nss_db, "-N", "--empty-password"],
            check=True,
        )

    subprocess.run(
        [
            "certutil",
            "-d",
            nss_db,
            "-A",
            "-t",
            "C,,",
            "-n",
            NSS_NICKNAME,
            "-i",
            str(cert),
        ],
        check=True,
    )
    return True


def uninstall_linux_nss(nss_db: str = DEFAULT_NSS_DB) -> bool:
    """Remove the CA from the Linux NSS database.

    Returns ``True`` if a deletion happened, ``False`` if ``certutil`` is
    missing or the cert was not present.
    """
    if not shutil.which("certutil"):
        return False

    result = subprocess.run(
        ["certutil", "-d", nss_db, "-D", "-n", NSS_NICKNAME],
        capture_output=True,
    )
    return result.returncode == 0


def is_in_macos_keychain() -> bool:
    result = subprocess.run(
        ["security", "find-certificate", "-c", CA_COMMON_NAME, MACOS_KEYCHAIN],
        capture_output=True,
    )
    return result.returncode == 0


def is_in_linux_system_trust(ca_dir: Path = DEFAULT_CA_DIR) -> bool:
    # update-ca-certificates symlinks our cert into /etc/ssl/certs/. If the
    # symlink exists we are trusted. We also accept the staged copy in
    # /usr/local/share/ca-certificates/ for the case where update-ca-certificates
    # has not run yet but install_linux_system already copied the file.
    return (
        LINUX_SYSTEM_CA_SYMLINK.exists()
        or (LINUX_SYSTEM_CA_DIR / LINUX_SYSTEM_CA_FILENAME).exists()
    )


def is_in_linux_nss(nss_db: str = DEFAULT_NSS_DB) -> bool | None:
    """Return True/False if the CA is in NSS, or None if certutil is missing."""
    if not shutil.which("certutil"):
        return None
    result = subprocess.run(
        ["certutil", "-L", "-d", nss_db, "-n", NSS_NICKNAME],
        capture_output=True,
    )
    return result.returncode == 0


def install_windows(cert: Path) -> None:
    """Install the CA to the Windows per-user Trusted Root store.

    Per-user (``-user``) doesn't need admin rights and is what Electron
    apps' NodeJS runtime checks via their bundled-then-OS lookup. The
    LocalMachine store would also work but requires elevation.
    """
    subprocess.run(
        ["certutil", "-user", "-addstore", "-f", WINDOWS_CERT_STORE, str(cert)],
        check=True,
    )


def uninstall_windows() -> None:
    """Remove the upbox CA from the Windows per-user Trusted Root store."""
    subprocess.run(
        ["certutil", "-user", "-delstore", WINDOWS_CERT_STORE, CA_COMMON_NAME],
        check=True,
    )


def is_in_windows_trust() -> bool:
    """Return True if the upbox CA is registered in the Windows per-user Root store."""
    result = subprocess.run(
        ["certutil", "-user", "-store", WINDOWS_CERT_STORE, CA_COMMON_NAME],
        capture_output=True,
    )
    return result.returncode == 0


def get_status(ca_dir: Path = DEFAULT_CA_DIR, nss_db: str = DEFAULT_NSS_DB) -> CAStatus:
    """Doctor check: does the CA exist on disk, and is each trust layer wired?"""
    cert = cert_path(ca_dir)
    system = platform.system()
    return CAStatus(
        cert_exists=cert.exists(),
        cert_path=cert,
        in_macos_keychain=is_in_macos_keychain() if system == "Darwin" else None,
        in_linux_system_trust=is_in_linux_system_trust(ca_dir) if system == "Linux" else None,
        in_linux_nss=is_in_linux_nss(nss_db) if system == "Linux" else None,
        nss_certutil_available=(
            shutil.which("certutil") is not None if system == "Linux" else None
        ),
        in_windows_trust=is_in_windows_trust() if system == "Windows" else None,
    )


def electron_app_hint(ca_dir: Path = DEFAULT_CA_DIR) -> str:
    """Shell hint for capturing AI traffic through the upbox proxy."""
    cert = cert_path(ca_dir)
    return (
        "To capture AI traffic, run:\n"
        "  upbox start\n"
        "upbox uses mitmproxy's LocalMode (OS network-layer redirector) to "
        "intercept HTTPS from every process on the machine — Wireshark-style. "
        "First run prompts for admin (driver/extension install). After that the "
        "OS handles capture transparently and unwinds cleanly on Ctrl+C.\n"
        "\n"
        "If LocalMode isn't available (no admin / unsupported), fall back to "
        "regular explicit-proxy mode:\n"
        '  upbox start --capture-spec ""\n'
        f"then route tools manually: HTTPS_PROXY=http://127.0.0.1:8888 "
        f"NODE_EXTRA_CA_CERTS={cert} <app>"
    )


def install_all(ca_dir: Path = DEFAULT_CA_DIR, nss_db: str = DEFAULT_NSS_DB) -> None:
    """Generate the CA if missing, then install to every applicable trust store."""
    cert, _ = generate_ca(ca_dir)
    system = platform.system()

    if system == "Darwin":
        install_macos(cert)
        print("[OK] Installed to macOS System keychain")
    elif system == "Linux":
        install_linux_system(cert)
        print("[OK] Installed to Linux system trust")
        if install_linux_nss(cert, nss_db):
            print("[OK] Installed to Linux NSS db")
        else:
            print("[WARN] certutil not found, skipped NSS install")
            print("       Debian/Ubuntu: sudo apt install libnss3-tools")
            print("       Fedora:        sudo dnf install nss-tools")
    elif system == "Windows":
        try:
            install_windows(cert)
            print("[OK] Installed to Windows per-user Trusted Root store")
        except subprocess.CalledProcessError:
            print("[ERR] certutil failed. Try opening an Administrator shell, or import")
            print(f"      {cert} manually into 'Trusted Root Certification Authorities'.")
    else:
        print(f"[WARN] Unsupported platform: {system}. Cert generated at {cert}.")

    print()
    print(electron_app_hint(ca_dir))


def uninstall_all(ca_dir: Path = DEFAULT_CA_DIR, nss_db: str = DEFAULT_NSS_DB) -> None:
    """Remove the CA from every trust store. The files in ``ca_dir`` stay so
    re-installing later doesn't need a new key. Delete the dir manually to wipe."""
    system = platform.system()

    if system == "Darwin":
        try:
            uninstall_macos()
            print("[OK] Removed from macOS System keychain")
        except subprocess.CalledProcessError:
            print("[WARN] Could not remove from macOS keychain (not installed?)")
    elif system == "Linux":
        try:
            uninstall_linux_system()
            print("[OK] Removed from Linux system trust")
        except subprocess.CalledProcessError:
            print("[WARN] Could not remove from Linux system trust")
        if uninstall_linux_nss(nss_db):
            print("[OK] Removed from Linux NSS db")
        else:
            print("[WARN] Could not remove from NSS db (not installed or certutil missing)")
    elif system == "Windows":
        try:
            uninstall_windows()
            print("[OK] Removed from Windows per-user Trusted Root store")
        except subprocess.CalledProcessError:
            print("[WARN] Could not remove from Windows trust store (not installed?)")

    print()
    print(f"Files in {ca_dir} were not deleted. Remove them manually to wipe the CA.")


def _nss_db_path(nss_db: str) -> Path:
    """Strip the ``sql:`` prefix that certutil expects and return the Path."""
    if nss_db.startswith("sql:"):
        return Path(nss_db[len("sql:") :])
    return Path(nss_db)


def write_mitmproxy_bundle(
    ca_dir: Path = DEFAULT_CA_DIR,
    confdir: Path = DEFAULT_MITM_CONFDIR,
) -> Path:
    """Write the combined-PEM (key + cert) that mitmproxy reads at startup.

    mitmproxy expects ``<confdir>/mitmproxy-ca.pem`` to contain both the
    private key and the certificate concatenated. Pointing it at a confdir
    we own (not ``~/.mitmproxy``) avoids stepping on a user's existing
    mitmproxy install.

    Returns the confdir path; pass it to ``Options(confdir=str(<path>))``.
    """
    cert = cert_path(ca_dir)
    key = key_path(ca_dir)
    if not (cert.exists() and key.exists()):
        raise FileNotFoundError(f"upbox CA not found in {ca_dir}. Run `upbox init` first.")

    confdir.mkdir(parents=True, exist_ok=True)
    confdir.chmod(0o700)

    bundle = confdir / MITM_CA_FILENAME
    bundle.write_bytes(key.read_bytes() + b"\n" + cert.read_bytes())
    bundle.chmod(0o600)
    return confdir
