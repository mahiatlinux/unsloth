#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p no-bad
python3 - <<'PY'
from pathlib import Path
import subprocess
plugin = subprocess.check_output(['gst-inspect-1.0', 'pulseaudio'], text=True)
plugin_file = next(line.split()[-1] for line in plugin.splitlines() if line.strip().startswith('Filename'))
bad = set(subprocess.check_output(['dpkg', '-L', 'gstreamer1.0-plugins-bad'], text=True).splitlines())
for path in Path(plugin_file).parent.glob('*.so'):
    target = Path('no-bad') / path.name
    if str(path) not in bad and not target.exists():
        target.symlink_to(path)
PY
GST_PLUGIN_SYSTEM_PATH_1_0="$PWD/no-bad" GST_REGISTRY_1_0="$PWD/no-bad-registry.bin" 
export GST_PLUGIN_SYSTEM_PATH_1_0 GST_REGISTRY_1_0
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a dbus-run-session -- /usr/bin/python3 probe.py > no-bad.log 2>&1
unset GST_PLUGIN_SYSTEM_PATH_1_0 GST_REGISTRY_1_0
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a dbus-run-session -- /usr/bin/python3 probe.py > installed.log 2>&1
