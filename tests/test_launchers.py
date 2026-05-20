"""Unit tests for the per-tool launchers (``upbox run <tool>``)."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from upbox import launchers


def test_find_tool_resolves_canonical_name() -> None:
    assert launchers.find_tool("claude-desktop") is not None


def test_find_tool_resolves_alias() -> None:
    tool = launchers.find_tool("claude")

    assert tool is not None and tool.name == "claude-desktop"


def test_find_tool_is_case_insensitive() -> None:
    assert launchers.find_tool("CURSOR") is not None


def test_find_tool_returns_none_for_unknown() -> None:
    assert launchers.find_tool("notreal") is None


def test_find_executable_returns_existing_path(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Claude.exe"
    fake_exe.touch()
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        paths_per_platform={sys.platform: (str(fake_exe),)},
    )

    assert launchers.find_executable(tool) == fake_exe


def test_find_executable_expands_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_exe = tmp_path / "Claude.exe"
    fake_exe.touch()
    monkeypatch.setenv("FAKE_APPDATA", str(tmp_path))
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        paths_per_platform={sys.platform: ("${FAKE_APPDATA}/Claude.exe",)},
    )

    assert launchers.find_executable(tool) == fake_exe


def test_find_executable_returns_none_when_missing() -> None:
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        paths_per_platform={sys.platform: ("/nonexistent/path/to/binary",)},
    )

    assert launchers.find_executable(tool) is None


def test_find_executable_falls_back_to_path_when_no_separators(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_exe = tmp_path / "claude"
    fake_exe.touch()
    fake_exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        paths_per_platform={sys.platform: ("claude",)},
    )

    assert launchers.find_executable(tool) == fake_exe


def test_build_child_env_sets_proxy_for_env_tools() -> None:
    tool = launchers.Tool(name="t", aliases=("t",), use_env_proxy=True)
    env = launchers.build_child_env(
        tool, "http://127.0.0.1:8888", Path("/etc/upbox-ca.pem"), base_env={}
    )

    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8888"


def test_build_child_env_skips_proxy_for_flag_tools() -> None:
    # Browsers (Chrome) receive --proxy-server on argv, not env.
    tool = launchers.Tool(name="t", aliases=("t",), use_env_proxy=False)
    env = launchers.build_child_env(
        tool, "http://127.0.0.1:8888", Path("/etc/upbox-ca.pem"), base_env={}
    )

    assert "HTTPS_PROXY" not in env


def test_build_args_substitutes_proxy_and_profile_placeholders() -> None:
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        extra_args=("--proxy-server={proxy}", "--user-data-dir={profile_dir}"),
    )
    args = launchers.build_args(
        tool, Path("/bin/chrome"), "http://127.0.0.1:8888", Path("/tmp/profile")
    )

    assert args == [
        "/bin/chrome",
        "--proxy-server=http://127.0.0.1:8888",
        "--user-data-dir=/tmp/profile",
    ]


def test_chrome_tool_has_proxy_server_flag() -> None:
    chrome = launchers.find_tool("chrome")

    assert chrome is not None and any("--proxy-server" in a for a in chrome.extra_args)


def test_launch_passes_proxy_env_to_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end: spawn a real Python child via launch(), have it dump its env
    # to a file, then verify HTTPS_PROXY landed in the child's environment.
    out = tmp_path / "env.json"
    probe = (
        "import json, os, sys; "
        f"json.dump({{k: os.environ.get(k) for k in ['HTTPS_PROXY','NODE_EXTRA_CA_CERTS']}}, "
        f"open(r'{out}', 'w'))"
    )
    tool = launchers.Tool(
        name="probe",
        aliases=("probe",),
        paths_per_platform={sys.platform: (sys.executable,)},
        extra_args=("-c", probe),
        use_env_proxy=True,
    )

    rc = launchers.launch(
        tool,
        proxy_host="127.0.0.1",
        proxy_port=8888,
        ca_path=Path("/fake/ca.pem"),
        profile_root=tmp_path / "profiles",
    )

    assert rc == 0
    assert json.loads(out.read_text())["HTTPS_PROXY"] == "http://127.0.0.1:8888"


def test_launch_raises_when_executable_missing(tmp_path: Path) -> None:
    tool = launchers.Tool(
        name="t",
        aliases=("t",),
        paths_per_platform={sys.platform: ("/nonexistent/binary",)},
    )

    with pytest.raises(FileNotFoundError):
        launchers.launch(tool, profile_root=tmp_path / "profiles")


def test_is_listening_returns_true_for_open_port() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert launchers.is_listening("127.0.0.1", port) is True
    finally:
        sock.close()


def test_is_listening_returns_false_for_closed_port() -> None:
    # Find a port that's almost certainly closed by binding then releasing.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    assert launchers.is_listening("127.0.0.1", port, timeout=0.2) is False


def test_wait_for_listening_times_out_when_port_never_opens() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    start = time.monotonic()

    result = launchers.wait_for_listening("127.0.0.1", port, timeout=0.5)

    assert result is False and (time.monotonic() - start) < 2.0
