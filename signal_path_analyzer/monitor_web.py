"""Live Signal Timing Monitor as a local web page (standard library only).

KiCad's bundled Python has no tkinter, so this is the default UI: a small HTTP server on
127.0.0.1 serves a page that polls /data every second and posts button actions back.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .chains import GroupResult

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>TraceForge - Signal Timing</title>
<style>
:root{--bg:#f6f7f9;--fg:#1f2733;--muted:#7a7f87;--ok:#1b7f3b;--warn:#b26a00;--bad:#c62828;--sel:#dbe7ff}
@media (prefers-color-scheme:dark){:root{--bg:#1e2228;--fg:#e6ebf2;--muted:#8a919c;--ok:#5fd28b;
--warn:#ffb454;--bad:#ff6b6b;--sel:#2c3a52}}
body{font:13px system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0}
header{position:sticky;top:0;background:var(--bg);padding:8px 12px;border-bottom:1px solid #8884;
display:flex;gap:6px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0 12px 0 0}button{font:inherit;padding:4px 10px;cursor:pointer}
#st{color:var(--muted);margin-left:auto}table{border-collapse:collapse;width:100%}
td,th{padding:3px 10px;text-align:right;font-variant-numeric:tabular-nums}
td:first-child,th:first-child{text-align:left}tr.g td{font-weight:600;border-top:1px solid #8884;
cursor:pointer}tr.c{cursor:pointer}tr.sel{background:var(--sel)}.ok{color:var(--ok)}
.short,.long{color:var(--warn)}.pending{color:var(--muted)}.stub{color:var(--bad)}
</style></head><body><header><h1>TraceForge &middot; Signal Timing</h1>
<button onclick="act('highlight')">Highlight chain</button>
<button onclick="act('highlight_group')">Highlight group</button>
<button onclick="act('clear')">Clear</button>
<button onclick="act('write')">Write DRC targets</button>
<button id="pz" onclick="paused=!paused;pz.textContent=paused?'Resume':'Pause'">Pause</button>
<span id="st"></span></header><table><thead><tr><th>Group / chain</th><th>Total ps</th>
<th>Target ps</th><th>&Delta; ps</th><th>P&minus;N ps</th><th>Stub ps</th><th>Status</th></tr>
</thead><tbody id="tb"></tbody></table><script>
let sel=null,paused=false,closed={};
const f=(v,s)=>v==null?'':(s&&v>0?'+':'')+v.toFixed(1);
async function act(a){if(!sel&&a!='clear'&&a!='write'){st.textContent='select a row first';return}
 const q=new URLSearchParams({a,group:sel?sel[0]:'',chain:sel&&sel[1]?sel[1]:''});
 const r=await fetch('/act?'+q,{method:'POST'});st.textContent=await r.text()}
function row(cls,cells,key){const tr=document.createElement('tr');tr.className=cls;
 if(sel&&key&&sel.join('\\t')==key.join('\\t'))tr.classList.add('sel');
 cells.forEach(([t,c])=>{const td=document.createElement('td');td.textContent=t;if(c)td.className=c;
 tr.appendChild(td)});tr.onclick=()=>{sel=key;if(cls=='g')closed[key[0]]=!closed[key[0]];draw()};
 tb.appendChild(tr)}
let data=[];function draw(){tb.innerHTML='';for(const g of data){
 row('g',[[(closed[g.name]?'▸ ':'▾ ')+g.name],[''],[f(g.target)],['spread '+f(g.spread)],[''],[''],
 [g.stubs?'stub! '+g.stubs:'',g.stubs?'stub':'']],[g.name]);if(closed[g.name])continue;
 for(const c of g.chains)row('c',[['   '+c.name],[f(c.total)],[f(c.target)],[f(c.delta,1)],
 [f(c.pair,1)],[f(c.stub),c.stub_bad?'stub':''],[c.status,c.status]],[g.name,c.name])}}
async function tick(){if(!paused){try{const r=await fetch('/data');const j=await r.json();
 if(j.error)st.textContent='waiting for KiCad: '+j.error;else{data=j.groups;draw();
 st.textContent='updated '+j.time+' ('+j.ms+' ms)'}}catch(e){st.textContent='monitor stopped'}}
 setTimeout(tick,1000)}tick();
</script></body></html>"""


def results_json(results: list[GroupResult]) -> list[dict]:
    out = []
    for g in results:
        out.append({"name": g.group.name, "target": g.target_ps, "spread": g.spread_ps,
                    "stubs": len(g.stub_violations), "chains": [
                        {"name": c.chain.name, "total": c.total_ps, "target": c.target_ps,
                         "delta": c.delta_ps, "pair": c.pair_skew_ps, "stub": c.stub_ps,
                         "status": c.status, "stub_bad": c.chain.name in g.stub_violations}
                        for c in g.chains]})
    return out


def serve(evaluate: Callable[[], list[GroupResult]], highlight_chain: Callable[[str, str], int],
          highlight_group: Callable[[str], int], clear: Callable[[], None],
          write_targets: Callable[[list[GroupResult]], str], open_browser: bool = True,
          idle_exit_s: float = 30.0) -> None:
    """Serve the dashboard until the page has not polled for `idle_exit_s` seconds."""

    state = {"results": [], "last_poll": time.time()}
    lock = threading.Lock()  # one IPC request at a time

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep KiCad's message panel quiet
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/data"):
                state["last_poll"] = time.time()
                t0 = time.perf_counter()
                try:
                    with lock:
                        state["results"] = evaluate()
                    body = {"groups": results_json(state["results"]),
                            "time": time.strftime("%H:%M:%S"),
                            "ms": round((time.perf_counter() - t0) * 1000)}
                except Exception as exc:  # KiCad closed or busy
                    body = {"error": str(exc)}
                self._send(json.dumps(body).encode(), "application/json")
            else:
                self._send(PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            action, group, chain = q.get("a"), q.get("group", ""), q.get("chain", "")
            try:
                with lock:
                    if action == "highlight" and chain:
                        msg = f"highlighted {highlight_chain(group, chain)} items"
                    elif action in ("highlight", "highlight_group") and group:
                        msg = f"highlighted {highlight_group(group)} items"
                    elif action == "clear":
                        clear()
                        msg = "selection cleared"
                    elif action == "write":
                        msg = write_targets(state["results"])
                    else:
                        msg = "select a chain or group row first"
            except Exception as exc:
                msg = f"failed: {exc}"
            self._send(msg.encode(), "text/plain; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"TraceForge Signal Timing Monitor: {url}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    try:
        while time.time() - state["last_poll"] < idle_exit_s:
            time.sleep(1)
    finally:
        server.shutdown()
