"""At-rest protection for the audit database.

upbox deliberately does not encrypt its own database. The reasoning is worth
stating plainly, because "encrypted at rest" is the kind of claim that sounds
strictly better than the alternative:

upbox runs as an unattended background daemon supervised by ``upbox start``, and
is expected to survive reboots. Any application-level encryption therefore needs
a key the daemon can reach without a human present, which in practice means a
key file sitting next to the database. That defeats ``strings upbox.db`` and
nothing else, while licensing a README claim that implies real protection. A
passphrase prompt at every start breaks unattended restart and gets disabled
within a week. An OS keychain is correct in principle but protects only against
an attacker who does not already have the unlocked user session, which is the
session the daemon runs in.

Meanwhile the threat that actually materialises for a laptop is theft or loss,
and FileVault, BitLocker and LUKS solve exactly that, at volume level, with keys
in a TPM or Secure Enclave that no Python process can match.

So: enforce owner-only permissions, report whether full-disk encryption is
actually on, and say clearly that the strongest control is not storing the data
at all (redaction and retention).
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Owner-only. On Windows these are largely inert (chmod only toggles the
# read-only bit), which is one more reason the honest answer is volume-level
# encryption rather than anything upbox does to a file mode.
DIR_MODE = 0o700
FILE_MODE = 0o600

_PROBE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class DiskEncryptionStatus:
    """Whether the volume holding the database is encrypted.

    ``state`` is ``encrypted``, ``not_encrypted``, or ``unknown``. Unknown is a
    real answer and is never smoothed over into a reassuring one.
    """

    state: str
    detail: str

    @property
    def is_encrypted(self) -> bool | None:
        if self.state == "encrypted":
            return True
        if self.state == "not_encrypted":
            return False
        return None


def harden_path_permissions(db_path: Path) -> None:
    """Restrict the database directory and files to the owner.

    Best effort by design: a filesystem that does not support POSIX modes, or a
    file owned by someone else, must not stop the proxy from running.
    """
    _chmod(db_path.parent, DIR_MODE)
    # -wal and -shm hold recently written rows and deserve the same mode.
    for suffix in ("", "-wal", "-shm"):
        _chmod(db_path.with_name(db_path.name + suffix), FILE_MODE)


def _chmod(path: Path, mode: int) -> None:
    try:
        if path.exists():
            path.chmod(mode)
    except OSError:
        # Reported by `upbox doctor` rather than raised: an audit tool that
        # refuses to start because of a file mode is worse than one that runs
        # and tells you the mode is wrong.
        pass


def path_mode(path: Path) -> str:
    """Octal permissions of ``path``, or a reason it could not be read."""
    try:
        return format(path.stat().st_mode & 0o777, "04o")
    except OSError as exc:
        return f"unreadable ({exc.strerror})"


def volume_encryption_status(path: Path) -> DiskEncryptionStatus:
    """Report whether the volume holding ``path`` is encrypted at rest."""
    system = platform.system()
    if system == "Darwin":
        return _macos_filevault_status()
    if system == "Windows":
        return _windows_bitlocker_status(path)
    if system == "Linux":
        return _linux_luks_status(path)
    return DiskEncryptionStatus("unknown", f"no automated check for platform {system!r}")


def _macos_filevault_status() -> DiskEncryptionStatus:
    result = _run(["fdesetup", "status"])
    if result is None:
        return DiskEncryptionStatus("unknown", "could not run `fdesetup status`")
    text = result.lower()
    if "filevault is on" in text:
        return DiskEncryptionStatus("encrypted", "FileVault is on")
    if "filevault is off" in text:
        return DiskEncryptionStatus(
            "not_encrypted", "FileVault is off; enable it in System Settings"
        )
    return DiskEncryptionStatus("unknown", f"unrecognised fdesetup output: {result.strip()[:80]}")


def _windows_bitlocker_status(path: Path) -> DiskEncryptionStatus:
    drive = path.drive or "C:"
    result = _run(["manage-bde", "-status", drive])
    if result is None:
        return DiskEncryptionStatus(
            "unknown", f"could not run `manage-bde -status {drive}` (needs an elevated shell)"
        )
    text = result.lower()
    if "percentage encrypted:  100" in text or "fully encrypted" in text:
        return DiskEncryptionStatus("encrypted", f"BitLocker is on for {drive}")
    if "fully decrypted" in text or "protection off" in text:
        return DiskEncryptionStatus("not_encrypted", f"BitLocker is off for {drive}")
    return DiskEncryptionStatus("unknown", f"unrecognised manage-bde output for {drive}")


def _linux_luks_status(path: Path) -> DiskEncryptionStatus:
    """Walk from the mountpoint's device up the lsblk tree looking for crypt.

    Reports unknown rather than guessing when lsblk is absent or the layout is
    not one this can read.
    """
    result = _run(["findmnt", "-n", "-o", "SOURCE", "--target", str(path)])
    if result is None:
        return DiskEncryptionStatus("unknown", "could not run `findmnt` to locate the device")
    source = result.strip()
    if not source:
        return DiskEncryptionStatus("unknown", "findmnt reported no source device")

    tree = _run(["lsblk", "-no", "NAME,TYPE", "--inverse", source])
    if tree is None:
        return DiskEncryptionStatus("unknown", f"could not run `lsblk` for {source}")
    if any(line.split()[-1] == "crypt" for line in tree.splitlines() if line.split()):
        return DiskEncryptionStatus("encrypted", f"{source} sits on a dm-crypt/LUKS device")
    return DiskEncryptionStatus(
        "not_encrypted", f"no dm-crypt layer under {source}; consider LUKS full-disk encryption"
    )


def _run(command: list[str]) -> str | None:
    """Run a probe, returning stdout or None if it could not be run."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 and not completed.stdout.strip():
        return None
    return completed.stdout
