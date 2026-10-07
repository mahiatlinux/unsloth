import os
assert os.environ.get('GDK_BACKEND') == 'x11'
assert 'WAYLAND_DISPLAY' not in os.environ
assert os.environ.get('DISPLAY') not in (None, ':0', ':0.0', ':1', ':1.0')
import gi, json
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib, Gdk
assert Gdk.Display.get_default().get_name() == os.environ['DISPLAY']
print('Isolated display:', Gdk.Display.get_default().get_name(), flush=True)
manager = WebKit2.UserContentManager()
manager.register_script_message_handler('result')
def result(manager, message):
    print(message.get_js_value().to_string(), flush=True)
    Gtk.main_quit()
manager.connect('script-message-received::result', result)
view = WebKit2.WebView(user_content_manager=manager)
view.get_settings().set_enable_media_stream(True)
def permission(view, req):
    if isinstance(req, WebKit2.UserMediaPermissionRequest):
        req.allow()
        return True
    return False
view.connect('permission-request', permission)
window = Gtk.Window()
window.add(view)
window.show_all()
view.load_html('''<script>
(async()=> {
 const result={};
 try {
  result.devices=(await navigator.mediaDevices.enumerateDevices()).map(d=>({kind:d.kind,label:d.label}));
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  result.track=stream.getAudioTracks()[0].readyState;
  const ctx=new AudioContext();
  const source=ctx.createMediaStreamSource(stream);
  result.context=ctx.state;
  result.mimeTypes=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].filter(t=>MediaRecorder.isTypeSupported(t));
  const recorder=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus'});
  result.bytes=0;
  recorder.addEventListener('dataavailable', e=>result.bytes+=e.data.size);
  const stopped=new Promise(resolve=>recorder.addEventListener('stop',resolve,{once:true}));
  result.recorder=recorder.mimeType;
  recorder.start(250);
  await new Promise(resolve=>setTimeout(resolve,2000));
  recorder.stop();
  await stopped;
  stream.getTracks().forEach(t=>t.stop());
  await ctx.close();
 } catch(e) {result.error={name:e.name,message:e.message};}
 window.webkit.messageHandlers.result.postMessage(JSON.stringify(result));
})();
</script>''', 'http://localhost/')
GLib.timeout_add_seconds(20, lambda: (print('TIMEOUT',flush=True),Gtk.main_quit(),False)[2])
Gtk.main()
