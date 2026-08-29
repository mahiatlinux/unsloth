# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved.

from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_SPEC = importlib.util.spec_from_file_location(
    "pr9890_studio_stage", REPO_ROOT / "unsloth_cli" / "_studio_stage.py"
)
assert STAGE_SPEC is not None and STAGE_SPEC.loader is not None
_studio_stage = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(_studio_stage)


OLD_VERSION = "2026.8.4"
NEW_VERSION = "2026.9.2"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}"
        )
    return result


def build_wheel(root: Path, version: str) -> Path:
    package = root / f"package-{version}"
    module = package / "unsloth_cli"
    module.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        'name = "unsloth"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.9"\n\n'
        "[project.scripts]\n"
        'unsloth = "unsloth_cli.__main__:main"\n',
        encoding="utf-8",
    )
    (module / "__init__.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    (module / "__main__.py").write_text(
        "from importlib.metadata import version\n\n"
        "def main():\n"
        "    print(version('unsloth'))\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    wheel_dir = root / f"wheels-{version}"
    wheel_dir.mkdir(exist_ok=True)
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(package),
        ]
    )
    built = set(wheel_dir.glob("*.whl"))
    if len(built) != 1:
        raise RuntimeError(f"expected one wheel for {version}, found {sorted(built)}")
    return built.pop()


def install_wheel(python: Path, wheel: Path) -> None:
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ]
    )


def installed_version(python: Path) -> str:
    return run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata as m; print(m.version('unsloth'))",
        ]
    ).stdout.strip()


def wait_for(path: Path, timeout: float = 30) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and (value := path.read_text(encoding="utf-8").strip()):
            return value
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {path}")


def stage_update(home: Path, wheel: Path) -> dict:
    def update(root: Path, _args: list[str]) -> int:
        install_wheel(_studio_stage.venv_python(root / _studio_stage.VENV_NAME), wheel)
        return 0

    return _studio_stage.stage(
        home,
        update_args=["--package", "unsloth"],
        echo=lambda line: print(line, flush=True),
        run_update=update,
    )


def interrupt_child(home: Path, marker: Path) -> None:
    def wait_forever(_root: Path, _args: list[str]) -> int:
        marker.write_text("staging\n", encoding="utf-8")
        time.sleep(600)
        return 0

    _studio_stage.stage(
        home,
        update_args=[],
        echo=lambda line: print(line, flush=True),
        run_update=wait_forever,
    )


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--interrupt-child":
        interrupt_child(Path(sys.argv[2]), Path(sys.argv[3]))
        return

    with tempfile.TemporaryDirectory(prefix="pr9890-updater-") as temporary:
        root = Path(temporary)
        home = root / "studio home"
        live = home / _studio_stage.VENV_NAME
        venv.EnvBuilder(with_pip=True).create(live)
        old_wheel = build_wheel(root, OLD_VERSION)
        new_wheel = build_wheel(root, NEW_VERSION)
        live_python = _studio_stage.venv_python(live)
        install_wheel(live_python, old_wheel)
        for helper in _studio_stage.HELPER_NAMES:
            helper_root = home / helper
            helper_root.mkdir(parents=True)
            (helper_root / "tag").write_text("live\n", encoding="utf-8")

        heartbeat = root / "heartbeat.txt"
        worker_code = (
            "import importlib.metadata as m,time,pathlib; "
            f"p=pathlib.Path({str(heartbeat)!r}); "
            "[(p.write_text(m.version('unsloth')), time.sleep(.05)) for _ in range(2400)]"
        )
        worker = subprocess.Popen([str(live_python), "-I", "-c", worker_code])
        try:
            assert wait_for(heartbeat) == OLD_VERSION
            stale = home / _studio_stage.STAGE_DIR_NAME / "stale"
            stale.mkdir(parents=True)
            (stale / "partial").write_text("partial\n", encoding="utf-8")

            result = stage_update(home, new_wheel)
            stage_root = Path(result["root"])
            staged_python = _studio_stage.venv_python(stage_root / _studio_stage.VENV_NAME)
            assert result["backend_version"] == NEW_VERSION
            assert installed_version(live_python) == OLD_VERSION
            assert installed_version(staged_python) == NEW_VERSION
            assert worker.poll() is None
            assert wait_for(heartbeat) == OLD_VERSION
            assert not stale.exists()
            ready = json.loads((stage_root / _studio_stage.READY_MARKER).read_text(encoding="utf-8"))
            assert ready["backend_version"] == NEW_VERSION
            for helper in _studio_stage.HELPER_NAMES:
                assert (stage_root / helper / "tag").read_text(encoding="utf-8").strip() == "live"
            print("PASS real older-to-newer stage is isolated while live backend runs")

            def fail_update(_root: Path, _args: list[str]) -> int:
                return 9

            try:
                _studio_stage.stage(home, update_args=[], echo=lambda _: None, run_update=fail_update)
            except _studio_stage.StageError as error:
                assert "staged update failed" in str(error)
            else:
                raise AssertionError("failed update was accepted")
            assert installed_version(live_python) == OLD_VERSION
            assert worker.poll() is None
            assert not (home / _studio_stage.STAGE_DIR_NAME).exists()
            print("PASS failed stage leaves the live backend and install untouched")

            def corrupt_update(stage: Path, _args: list[str]) -> int:
                stage_python = _studio_stage.venv_python(stage / _studio_stage.VENV_NAME)
                install_wheel(stage_python, new_wheel)
                site = run(
                    [
                        str(stage_python),
                        "-I",
                        "-c",
                        "import pathlib,unsloth_cli; print(pathlib.Path(unsloth_cli.__file__).parent)",
                    ]
                ).stdout.strip()
                Path(site, "__main__.py").unlink()
                return 0

            try:
                _studio_stage.stage(home, update_args=[], echo=lambda _: None, run_update=corrupt_update)
            except _studio_stage.StageError:
                pass
            else:
                raise AssertionError("corrupt staged package was accepted")
            assert installed_version(live_python) == OLD_VERSION
            assert not (home / _studio_stage.STAGE_DIR_NAME).exists()
            print("PASS corrupt staged package is rejected and removed")

            marker = root / "child-staging.txt"
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--interrupt-child", str(home), str(marker)]
            )
            wait_for(marker)
            child.terminate()
            child.wait(timeout=30)
            assert installed_version(live_python) == OLD_VERSION
            assert worker.poll() is None
            assert (home / _studio_stage.STAGE_DIR_NAME).exists()
            stage_update(home, new_wheel)
            assert installed_version(live_python) == OLD_VERSION
            print("PASS interrupted stage is recovered on the next attempt")

            _studio_stage.discard(home / _studio_stage.STAGE_DIR_NAME)
            original_disk_usage = _studio_stage.shutil.disk_usage
            disk_usage_type = type(original_disk_usage(home))
            _studio_stage.shutil.disk_usage = lambda _path: disk_usage_type(10, 10, 0)
            try:
                try:
                    stage_update(home, new_wheel)
                except _studio_stage.StageError as error:
                    assert "not enough free disk space" in str(error)
                else:
                    raise AssertionError("zero free space was accepted")
            finally:
                _studio_stage.shutil.disk_usage = original_disk_usage
            assert installed_version(live_python) == OLD_VERSION
            print("PASS insufficient disk space fails before cloning")

            if os.name != "nt":
                home.chmod(0o500)
                try:
                    try:
                        stage_update(home, new_wheel)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("unwritable stage root was accepted")
                finally:
                    home.chmod(0o700)
                assert installed_version(live_python) == OLD_VERSION
                print("PASS permission failure leaves live install usable")
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)


if __name__ == "__main__":
    main()
