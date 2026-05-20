"""Per-tool launchers that spawn AI tools through the upbox proxy.

Cross-platform replacement for setting ``HTTPS_PROXY`` / ``NODE_EXTRA_CA_CERTS``
by hand. ``upbox run <tool>`` finds the tool's executable, then spawns it as
a child process with the proxy env vars (or browser proxy flags) set, so only
that one process is routed through upbox.

Why not toggle system proxy? Two reasons. First, a crashed upbox would leave
the OS pointing at a dead 127.0.0.1:8888 and break the user's internet until
they manually undid it. Second, capturing every HTTPS request on the box (OS
telemetry, browser, app updates) buries the AI traffic upbox actually exists
to audit.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

CA_PATH_DEFAULT = Path.home() / ".upbox" / "ca" / "upbox-ca.pem"
PROFILE_ROOT_DEFAULT = Path.home() / ".upbox" / "profiles"


@dataclass
class Tool:
    """A single launchable AI tool."""

    name: str
    aliases: tuple[str, ...]
    paths_per_platform: dict[str, tuple[str, ...]] = field(default_factory=dict)
    extra_args: tuple[str, ...] = ()
    # Browsers ignore HTTPS_PROXY env vars and need a CLI flag instead.
    use_env_proxy: bool = True

    def paths(self) -> tuple[str, ...]:
        return self.paths_per_platform.get(sys.platform, ())


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="claude-desktop",
        aliases=("claude", "claude-desktop"),
        paths_per_platform={
            "win32": (
                r"%LOCALAPPDATA%\AnthropicClaude\Claude.exe",
                r"%LOCALAPPDATA%\Programs\Claude\Claude.exe",
            ),
            "darwin": ("/Applications/Claude.app/Contents/MacOS/Claude",),
            "linux": (
                "/usr/bin/claude-desktop",
                "/opt/Claude/claude-desktop",
            ),
        },
    ),
    Tool(
        name="claude-code",
        aliases=("claude-code",),
        # `claude` is the npm-installed CLI from @anthropic-ai/claude-code.
        paths_per_platform={
            "win32": ("claude.cmd", "claude.exe"),
            "darwin": ("claude",),
            "linux": ("claude",),
        },
    ),
    Tool(
        name="cursor",
        aliases=("cursor",),
        paths_per_platform={
            "win32": (r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe",),
            "darwin": ("/Applications/Cursor.app/Contents/MacOS/Cursor",),
            "linux": ("/usr/bin/cursor", "/opt/Cursor/cursor"),
        },
    ),
    Tool(
        name="vscode",
        aliases=("vscode", "code"),
        # Covers Copilot and Codeium since both ship as VS Code extensions.
        paths_per_platform={
            "win32": (
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
                r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
            ),
            "darwin": ("/Applications/Visual Studio Code.app/Contents/MacOS/Electron",),
            "linux": ("/usr/bin/code", "/usr/share/code/code"),
        },
    ),
    Tool(
        name="chrome",
        aliases=("chrome", "google-chrome"),
        paths_per_platform={
            "win32": (
                r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
                r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
            ),
            "darwin": ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",),
            "linux": (
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
            ),
        },
        # --user-data-dir isolates from the user's main profile so existing
        # logins/cookies aren't disturbed and the proxy setting can't leak
        # back into normal browsing after the child exits.
        extra_args=(
            "--proxy-server={proxy}",
            "--user-data-dir={profile_dir}",
        ),
        use_env_proxy=False,
    ),
)


def find_tool(alias: str) -> Tool | None:
    """Resolve a user-supplied alias to a Tool, or None if unknown."""
    needle = alias.lower()
    for t in TOOLS:
        if needle == t.name.lower() or needle in (a.lower() for a in t.aliases):
            return t
    return None


def find_executable(tool: Tool) -> Path | None:
    """Return the first existing executable path for this platform, or None.

    Each candidate is expanded for ``$VAR`` / ``%VAR%`` / ``~``. If a
    candidate has no path separators, it's treated as a name to look up on
    ``PATH`` (so ``"claude"`` resolves via ``shutil.which``).
    """
    for raw in tool.paths():
        expanded = _expand(raw)
        if "/" not in expanded and "\\" not in expanded:
            which = shutil.which(expanded)
            if which:
                return Path(which)
            continue
        p = Path(expanded)
        if p.is_file():
            return p
    return None


def _expand(raw: str) -> str:
    return os.path.expandvars(os.path.expanduser(raw))


def build_child_env(
    tool: Tool,
    proxy_url: str,
    ca_path: Path,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the env dict the child should run with."""
    env = dict(base_env if base_env is not None else os.environ)
    if tool.use_env_proxy:
        env["HTTPS_PROXY"] = proxy_url
        env["HTTP_PROXY"] = proxy_url
        env["NODE_EXTRA_CA_CERTS"] = str(ca_path)
    return env


def build_args(
    tool: Tool,
    exe: Path,
    proxy_url: str,
    profile_dir: Path,
) -> list[str]:
    """Build the argv for the child process, substituting ``{proxy}`` and
    ``{profile_dir}`` in ``tool.extra_args``. Plain string replacement so
    we don't conflict with arbitrary user args that contain braces.
    """
    formatted = [
        a.replace("{proxy}", proxy_url).replace("{profile_dir}", str(profile_dir))
        for a in tool.extra_args
    ]
    return [str(exe), *formatted]


def is_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if something is accepting connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_listening(
    host: str,
    port: int,
    timeout: float = 15.0,
    sentinel: subprocess.Popen[bytes] | None = None,
) -> bool:
    """Poll until ``host:port`` accepts a connection, or until ``timeout``.

    If ``sentinel`` is a Popen and it exits before the port opens, give up
    early — it means the supervisor we started has died.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_listening(host, port):
            return True
        if sentinel is not None and sentinel.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def launch(
    tool: Tool,
    proxy_host: str = "127.0.0.1",
    proxy_port: int = 8888,
    ca_path: Path = CA_PATH_DEFAULT,
    profile_root: Path = PROFILE_ROOT_DEFAULT,
) -> int:
    """Spawn ``tool`` routed through the upbox proxy. Returns the child's rc.

    Raises ``FileNotFoundError`` if the executable can't be located.
    """
    exe = find_executable(tool)
    if exe is None:
        looked_in = ", ".join(tool.paths()) or "(no paths registered for this platform)"
        raise FileNotFoundError(
            f"Could not locate {tool.name} on {sys.platform}. "
            f"Looked in: {looked_in}. Install it, or add its path."
        )

    proxy_url = f"http://{proxy_host}:{proxy_port}"
    profile_dir = profile_root / tool.name
    profile_dir.mkdir(parents=True, exist_ok=True)

    env = build_child_env(tool, proxy_url, ca_path)
    args = build_args(tool, exe, proxy_url, profile_dir)

    proc = subprocess.Popen(args, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()
