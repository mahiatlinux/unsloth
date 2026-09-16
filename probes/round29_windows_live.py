import subprocess
import sys
import os
import json
import shlex
import socket
import threading
import time
from pathlib import Path
import paramiko
from core.inference.tools import _bash_exec, _python_exec, _get_workdir

try:
    from state.ssh_approvals import approve_hosts
except ImportError:
    approve_hosts = lambda *args: None

host_key = paramiko.RSAKey.generate(2048)
client_key = paramiko.RSAKey.generate(2048)
listener = socket.socket()
listener.bind(('127.0.0.1', 22222))
listener.listen()
listener.settimeout(.1)
port = listener.getsockname()[1]
connections = []
stop = threading.Event()

class Server(paramiko.ServerInterface):
    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL if key == client_key else paramiko.AUTH_FAILED
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL
    def get_allowed_auths(self, username):
        return 'publickey,password'
    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED
    def check_channel_exec_request(self, channel, command):
        def reply():
            channel.send(b'pr10642-live-ssh-ok\n')
            channel.send_exit_status(0)
            channel.shutdown_write()
            time.sleep(.1)
            channel.close()
        threading.Thread(target=reply, daemon=True).start()
        return True

def serve_client(sock):
    transport = paramiko.Transport(sock)
    transport.add_server_key(host_key)
    transport.set_subsystem_handler("sftp",paramiko.SFTPServer,paramiko.SFTPServerInterface)
    try:
        transport.start_server(server=Server())
        channel = transport.accept(8)
        if channel:
            while transport.is_active() and not stop.wait(.05):
                pass
    except Exception as exc:
        print(type(exc).__name__, str(exc))
    finally:
        transport.close()

def serve():
    while not stop.is_set():
        try:
            sock, addr = listener.accept()
        except socket.timeout:
            continue
        connections.append(addr)
        threading.Thread(target=serve_client,args=(sock,),daemon=True).start()
server_thread=threading.Thread(target=serve,daemon=True)
server_thread.start()
from core.inference import tools as tools_mod
assert sys.platform=='win32'
tools_mod._windows_bash=lambda:None
assert tools_mod._get_shell_cmd('echo ok')==['cmd','/c','echo ok']
session = 'ssh-live'
root = Path(_get_workdir(session))
client_key.write_private_key_file(str(root/'review-key'))
(root/'review-key').chmod(0o600)
subprocess.run(['icacls',str(root/'review-key'),'/inheritance:r','/grant:r',os.environ['USERNAME']+':(R)'],check=True,capture_output=True)
ssh_path=Path(os.environ['SystemRoot'])/'System32'/'OpenSSH'/'ssh.exe'
assert ssh_path.is_file()
command = f'{ssh_path.with_suffix("")} -F none -p {port} -i review-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o IdentitiesOnly=yes review@127.0.0.1 uptime'
command='set PROGRAMDATA='+os.environ.get('ProgramData',r'C:\ProgramData')+'&echo ok&'+command
safe_env=tools_mod._build_safe_env(str(root))
for label,extra in [('original',{}),('programdata',{'ProgramData':os.environ.get('ProgramData',r'C:\ProgramData')}),('profile',{'USERPROFILE':str(root),'USERNAME':os.environ['USERNAME']})]:
 probe=subprocess.run([str(ssh_path),'-V'],env=safe_env|extra,capture_output=True,text=True)
 print(json.dumps({'probe':label,'returncode':probe.returncode,'stdout':probe.stdout,'stderr':probe.stderr}),flush=True)
command=command.replace('LogLevel=ERROR','LogLevel=DEBUG3')
result=_bash_exec(command,session_id=session,timeout=10)
print(json.dumps({'platform':sys.platform,'shell':tools_mod._get_shell_cmd(command)[:2],'command':command,'before':result,'connections':len(connections)}),flush=True)
if '--negative' in sys.argv:
 assert 'pr10642-live-ssh-ok' in result and len(connections)==1
else:
 assert 'Blocked' in result and not connections
 if '--base' not in sys.argv:
  approve_hosts(session,['127.0.0.1'])
  result=_bash_exec(command,session_id=session,timeout=10)
  print(json.dumps({'after':result,'connections':len(connections)}),flush=True)
  assert 'pr10642-live-ssh-ok' in result and len(connections)==1
stop.set();server_thread.join(timeout=2);listener.close()
