import os,sys,time,json,subprocess,threading
from pathlib import Path
out=Path('native-drop-evidence').resolve();out.mkdir(exist_ok=True)
fixture=out/'probe.txt';fixture.write_text('Cross-platform native file drop probe.\n')
exe=Path('studio/src-tauri/target/debug/unsloth-studio'+('.exe' if sys.platform=='win32' else '')).resolve()
env=os.environ.copy();env['DROP_PROBE_OUT']=str(out)
log=(out/'app.log').open('w')
app=subprocess.Popen([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT)
try:
 for _ in range(120):
  if (out/'ready.json').exists():break
  if app.poll() is not None:raise RuntimeError('App exited: '+str(app.returncode))
  time.sleep(.5)
 else:raise RuntimeError('Native webview did not register listeners')
 from PySide6.QtWidgets import QApplication,QWidget,QLabel,QVBoxLayout
 from PySide6.QtGui import QDrag
 from PySide6.QtCore import Qt,QMimeData,QUrl,QTimer
 import pyautogui
 class Source(QWidget):
  def mousePressEvent(self,event):
   print('Starting OS file drag',flush=True)
   mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(fixture))])
   drag=QDrag(self);drag.setMimeData(mime)
   action=drag.exec(Qt.DropAction.CopyAction)
   print('Native drag action',action,flush=True)
 qt=QApplication([]);source=Source();source.setWindowTitle('File drag source')
 source.setGeometry(20,60,200,140)
 label=QLabel('Drag probe.txt');label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
 layout=QVBoxLayout(source);layout.addWidget(label);source.show();source.raise_()
 def drive():
  time.sleep(3)
  pyautogui.screenshot().save(str(out/'before.png'))
  pyautogui.moveTo(120,130);pyautogui.dragTo(650,400,duration=2,button='left')
  time.sleep(3)
  pyautogui.screenshot().save(str(out/'after.png'))
 threading.Thread(target=drive,daemon=True).start()
 timer=QTimer();started=time.monotonic()
 def poll():
  if (out/'result.json').exists() or time.monotonic()-started>30:qt.quit()
 timer.timeout.connect(poll);timer.start(500);qt.exec()
 if not (out/'result.json').exists():raise RuntimeError('No OS drop received; inspect screenshots and runner input permissions')
 result=json.loads((out/'result.json').read_text());print(json.dumps(result,indent=2))
 assert result['webviewDrops']==1,result
 assert result['windowDrops']==0,result
 assert result.get('registration') and not result.get('error'),result
 print('PASS: real OS drop reaches main webview and authorizes native attachment intake')
finally:
 app.terminate()
 try:app.wait(timeout=10)
 except subprocess.TimeoutExpired:app.kill()
 log.close()
