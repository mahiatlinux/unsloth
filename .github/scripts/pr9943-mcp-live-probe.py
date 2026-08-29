#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_unsloth_bin(home: Path) -> Path:
    candidates = [
        home / "bin" / "unsloth",
        home / "bin" / "unsloth.exe",
        home / "unsloth_studio" / "bin" / "unsloth",
        home / "unsloth_studio" / "Scripts" / "unsloth.exe",
    ]
    candidates.extend(home.glob(".venv*/*/unsloth"))
    candidates.extend(home.glob(".venv*/Scripts/unsloth.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"could not find unsloth CLI under {home}")


def find_studio_python(home: Path) -> Path:
    candidates = [
        home / "unsloth_studio" / "bin" / "python",
        home / "unsloth_studio" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"could not find managed Studio Python under {home}")


def wait_for_health(base_url: str, timeout: float = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/api/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    raise AssertionError("Studio did not become healthy")


def read_bootstrap_password(home: Path, log_path: Path) -> str:
    for relative in ("auth/.bootstrap_password", ".bootstrap_password"):
        path = home / relative
        if path.is_file():
            password = path.read_text(encoding="utf-8").strip()
            if password:
                return password
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"(?i)(?:bootstrap|initial|generated)\s*password.*?[:=]\s*(\S+)", text)
    if match:
        return match.group(1).strip().strip(".,")
    raise AssertionError("could not read Studio bootstrap password")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    home = Path(os.environ["UNSLOTH_STUDIO_HOME"]).resolve()
    artifact_dir = Path(os.environ["STUDIO_ARTIFACT_DIR"]).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "studio.log"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    launch_env = os.environ.copy()
    launch_env["UNSLOTH_STUDIO_ALLOW_STDIO_MCP"] = "1"
    launch_env["UNSLOTH_STUDIO_NO_FILE_LOG"] = "1"
    launch_kwargs: dict = {"env": launch_env}
    if os.name == "nt":
        launch_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        launch_kwargs["start_new_session"] = True
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(find_unsloth_bin(home)), "studio", "-H", "127.0.0.1", "-p", str(port)],
            cwd=workspace,
            stdout=log,
            stderr=subprocess.STDOUT,
            **launch_kwargs,
        )
    try:
        wait_for_health(base_url)
        probe_env = os.environ.copy()
        probe_env.update(
            {
                "BASE_URL": base_url,
                "STUDIO_OLD_PW": read_bootstrap_password(home, log_path),
                "STUDIO_NEW_PW": "McpArgumentCi!42",
                "STUDIO_MCP_PYTHON": str(find_studio_python(home)),
                "PW_ART_DIR": str(artifact_dir / "playwright"),
                "STUDIO_PLAYWRIGHT_BROWSER": os.environ.get("STUDIO_BROWSER", "chromium"),
            }
        )
        subprocess.run(
            [sys.executable, "tests/studio/playwright_mcp_arguments.py"],
            cwd=workspace,
            env=probe_env,
            check=True,
        )
        print("PASS real MCP argument Studio flow", flush=True)
        return 0
    finally:
        stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
