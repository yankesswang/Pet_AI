"""以 CDP 逐頁截圖 VetLink AI Demo，供簡報使用。"""
import json, subprocess, time, base64, urllib.request, os, sys, shutil
import websocket

URL = os.environ.get("SHOOT_URL", "http://localhost:5173/")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("SHOOT_OUT", os.path.join(REPO_ROOT, "docs", "screenshots"))
PORT = 9222
VIEWS = [("compare","05_compare"),("overview","00_overview"),("act1","01_act1_red"),("amber","02_amber"),
         ("act2","03_act2_blue"),("act3","04_act3_replay")]

chrome = (
    shutil.which("google-chrome")
    or shutil.which("chromium-browser")
    # macOS 的 Chrome 不在 PATH 上
    or next((c for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
             if os.path.exists(c)), None)
)
if not chrome:
    sys.exit("找不到 Chrome／Chromium，請設定 PATH 或安裝後再執行。")
proc = subprocess.Popen([chrome,"--headless=new","--disable-gpu","--no-sandbox",
    f"--remote-debugging-port={PORT}","--remote-allow-origins=*","--hide-scrollbars","--force-device-scale-factor=2",
    "--window-size=1500,1000", URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def targets():
    for _ in range(40):
        try:
            return json.load(urllib.request.urlopen(f"http://localhost:{PORT}/json"))
        except Exception:
            time.sleep(0.5)
    raise SystemExit("chrome did not start")

page = next(t for t in targets() if t["type"]=="page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=40)
_id = [0]
def cmd(method, **params):
    _id[0]+=1
    ws.send(json.dumps({"id":_id[0],"method":method,"params":params}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==_id[0]:
            if "error" in m: raise RuntimeError(m["error"])
            return m.get("result",{})

cmd("Page.enable"); cmd("Runtime.enable")
time.sleep(3.5)

def js(expr):
    r = cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    return r.get("result",{}).get("value")

os.makedirs(OUT, exist_ok=True)
for vid, name in VIEWS:
    # 點擊對應分頁：以按鈕文字比對 VIEWS 的 kicker
    clicked = js(f"""(() => {{
        const btns=[...document.querySelectorAll('button,a,[role=tab]')];
        const map={{compare:'對照',overview:'四種狀態總覽',act1:'系統拒絕用藥要求',amber:'資訊不足時的追問',
                   act2:'同案例、不同角色',act3:'仿單更新追回舊回答'}};
        const t=map['{vid}'];
        const b=btns.find(x=>(x.textContent||'').includes(t));
        if(b){{b.click();return true;}} return false;
    }})()""")
    time.sleep(2.0)
    # 觸發該幕的主要互動，讓判定結果實際呈現（否則只截到未送出的初始畫面）
    for _ in range(0 if vid=='overview' else 4):
        did = js("""(() => {
            const kw=['送出並執行','掃描飼主 QR Code','掃描飼主','執行影響回溯','上傳新版','送出','解鎖','開始','執行'];
            const btns=[...document.querySelectorAll('button')]
              .filter(b=>!b.disabled && b.offsetParent!==null);
            for(const k of kw){
              const b=btns.find(x=>(x.textContent||'').includes(k));
              if(b){b.click();return (b.textContent||'').trim().slice(0,24);}
            }
            return null;
        })()""")
        if not did: break
        time.sleep(2.0)
    time.sleep(1.5)
    m = cmd("Page.getLayoutMetrics")
    h = int(m["cssContentSize"]["height"]); w = int(m["cssContentSize"]["width"])
    cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2, mobile=False)
    time.sleep(1.2)
    data = cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]
    p = os.path.join(OUT, f"{name}.png")
    open(p,"wb").write(base64.b64decode(data))
    cmd("Emulation.clearDeviceMetricsOverride")
    print(f"{name:20} clicked={clicked} {w}x{h} -> {os.path.getsize(p)//1024}KB")

ws.close(); proc.terminate()
