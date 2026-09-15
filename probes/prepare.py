from pathlib import Path
import os
root=Path.cwd().resolve()
source=root.parent/'driver/probes'
target=root/'.review-probes'
target.mkdir(exist_ok=True)
for name in ['ui_server.py','live_ssh.py','ui_scene.py']:
    text=(source/name).read_text().replace('/work',root.as_posix()).replace('/evidence',target.as_posix())
    (target/name).write_text(text)
