import json
import os
import subprocess
import sys
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

# expect: the base tool result remains hard-blocked after approval; the head displays the real SSH output.
base = 'http://127.0.0.1:8010'
out = Path('/work/ui-evidence'); out.mkdir(exist_ok=True)
log = (out/'server.log').open('w')
server = subprocess.Popen([sys.executable, '/evidence/ui_server.py'], stdout=log, stderr=log)
try:
    for _ in range(120):
        try:
            if requests.get(base+'/healthz',timeout=1).ok:
                break
        except requests.RequestException:
            pass
        if server.poll() is not None:
            raise RuntimeError('server exited: '+(out/'server.log').read_text()[-1800:])
        time.sleep(.5)
    boot = Path('/work/.home/studio/auth/.bootstrap_password')
    password = boot.read_text().strip() if boot.exists() else 'Disposable-10642-Review!'
    r=requests.post(base+'/api/auth/login',json={'username':'unsloth','password':password}); r.raise_for_status()
    token=r.json()['access_token']
    if boot.exists():
        r=requests.post(base+'/api/auth/change-password',headers={'Authorization':'Bearer '+token},json={'current_password':password,'new_password':'Disposable-10642-Review!'}); r.raise_for_status()
    auth=r.json(); headers={'Authorization':'Bearer '+auth['access_token']}
    report=json.loads(Path('/work/live-result.json').read_text())
    # preserve the executed result verbatim; the warning text is part of OpenSSH output.
    output=report['terminal_after']
    thread='pr10642-ui-evidence'
    r=requests.post(base+'/api/chat/threads',headers=headers,json={'id':thread,'title':'Approved SSH deployment','modelType':'base','modelId':'','createdAt':1789516800000}); r.raise_for_status()
    messages=[
      {'id':'user-1','threadId':thread,'role':'user','content':[{'type':'text','text':'Connect to the approved deployment server and run uptime.'}],'createdAt':1789516800000},
      {'id':'assistant-1','parentId':'user-1','threadId':thread,'role':'assistant','content':[{'type':'tool-call','toolCallId':'ssh-1','toolName':'terminal','args':{'command':report['command']},'argsText':json.dumps({'command':report['command']}),'result':output}], 'createdAt':1789516801000}
    ]
    r=requests.put(base+f'/api/chat/threads/{thread}/messages',headers=headers,json={'messages':messages}); r.raise_for_status()
    with sync_playwright() as pw:
      for engine in ['chrome','msedge']:
        browser=pw.chromium.launch(channel=engine)
        context=browser.new_context(viewport={'width':1280,'height':900},locale='en-US',color_scheme='light',reduced_motion='reduce')
        context.add_init_script('localStorage.setItem("unsloth_auth_token", '+json.dumps(auth['access_token'])+');localStorage.setItem("unsloth_auth_refresh_token", '+json.dumps(auth['refresh_token'])+');')
        page=context.new_page()
        page.goto(base+'/chat',wait_until='networkidle')
        print('initial',page.url,page.locator('body').inner_text()[:1200],flush=True)
        page.get_by_text('Approved SSH deployment',exact=True).first.click()
        time.sleep(1)
        print('thread',page.url,page.locator('body').inner_text()[-1800:],flush=True)
        marker='Blocked command(s) for safety: ssh' if report['connections']==0 else 'pr10642-live-ssh-ok'
        try:
            page.get_by_text(marker,exact=False).first.wait_for(state='visible',timeout=5000)
        except Exception:
            buttons=page.get_by_role('button').all()
            for button in buttons:
                text=button.inner_text()
                if 'ssh' in text or 'terminal' in text.lower():
                    button.click()
                    break
            page.get_by_text(marker,exact=False).first.wait_for(state='visible',timeout=5000)
        page.screenshot(path=str(out/(engine+'.png')),full_page=True)
        (out/(engine+'.json')).write_text(json.dumps({'browser':engine,'version':browser.version,'marker':marker,'result':output,'url':page.url,'viewport':[1280,900]},indent=2))
        context.close(); browser.close()
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    driver=webdriver.Safari()
    try:
        driver.set_window_size(1280,1000)
        driver.get(base+'/login')
        driver.execute_script("localStorage.setItem('unsloth_auth_token',arguments[0]);localStorage.setItem('unsloth_auth_refresh_token',arguments[1]);",auth['access_token'],auth['refresh_token'])
        driver.get(base+'/chat?thread='+thread)
        wait=WebDriverWait(driver,45)
        wait.until(lambda d:'Connect to the approved deployment server' in d.execute_script("return document.body ? document.body.innerText : ''"))
        marker='Blocked command(s) for safety: ssh' if report['connections']==0 else 'pr10642-live-ssh-ok'
        if marker not in driver.execute_script("return document.body ? document.body.innerText : ''"):
            buttons=driver.find_elements(By.TAG_NAME,'button')
            for button in buttons:
                if 'ssh' in button.text:
                    button.click()
                    break
        wait.until(lambda d:marker in d.execute_script("return document.body ? document.body.innerText : ''"))
        driver.save_screenshot(str(out/'safari.png'))
        (out/'safari.json').write_text(json.dumps({'browser':'Safari','version':driver.capabilities['browserVersion'],'marker':marker,'viewport':driver.execute_script('return [innerWidth,innerHeight]')},indent=2))
    finally:
        driver.quit()
finally:
    server.terminate()
    try: server.wait(timeout=10)
    except subprocess.TimeoutExpired: server.kill();server.wait()
