from pathlib import Path
import subprocess
p=Path('studio/frontend/src/features/native-intents/native-drop-targets.ts')
original=p.read_text()
try:
    p.write_text(original.replace('getCurrentWebview().onDragDropEvent', 'getCurrentWindow().onDragDropEvent'))
    r=subprocess.run(['node','--experimental-strip-types','--test','tests/native-drop-webview-routing.test.ts'],cwd='studio/frontend',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(r.stdout)
    assert r.returncode != 0, 'Old window routing incorrectly passed'
    assert 'native targets receive main-webview drops' in r.stdout and 'true' in r.stdout, 'Unexpected failure'
    print('PASS: old window routing fails the real-SDK delivery test')
finally:
    p.write_text(original)
