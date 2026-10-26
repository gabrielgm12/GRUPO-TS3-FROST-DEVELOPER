#!/usr/bin/env python3
"""Painel local para setar grupos do TeamSpeak 3 via ClientQuery (porta 25639).
Uso: python3 server.py   ->  abre http://127.0.0.1:8765
"""
import json, os, socket, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.name == "nt"
DATA = os.environ.get("GRUPOS_DATA") or (os.path.join(os.environ.get("APPDATA", HERE), "GruposTS3") if WIN else HERE)
URL = "http://127.0.0.1:8765"
last_ping = [0.0]
os.makedirs(DATA, exist_ok=True)
sys.path.insert(0, HERE)

# --- atualização automática: se há uma versão mais nova baixada em <dados>/current, roda ela ---
if os.environ.get("GRUPOS_BOOT") != "1":
    try:
        import updater as _u
        _cur = os.path.join(DATA, "current")
        if os.path.exists(os.path.join(_cur, "server.py")) and _u.vt(_u.read_version(_cur)) > _u.vt(_u.read_version(HERE)):
            os.environ["GRUPOS_BOOT"] = "1"
            sys.modules.pop("updater", None)  # a versão nova usa o updater.py novo
            sys.path.insert(0, _cur)
            import runpy
            runpy.run_path(os.path.join(_cur, "server.py"), run_name="__main__")
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as _e:  # pacote quebrado: ignora e roda a versão instalada
        print("atualização ignorada:", _e)

import updater
VERSION = updater.read_version(HERE)
CONFIG = os.path.join(DATA, "config.json")
PRESETS = os.path.join(DATA, "presets.json")
LEARNED = os.path.join(DATA, "perms.json")  # {sgid: {"add": bool, "rem": bool}} aprendido nas tentativas
LOCK = threading.Lock()

ESC = [("\\", "\\\\"), ("/", "\\/"), (" ", "\\s"), ("|", "\\p"), ("\n", "\\n"), ("\t", "\\t")]


def esc(s):
    for a, b in ESC:
        s = s.replace(a, b)
    return s


def unesc(s):
    out, i = "", 0
    m = {"s": " ", "p": "|", "/": "/", "\\": "\\", "n": "\n", "t": "\t"}
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out += m.get(s[i + 1], s[i + 1])
            i += 2
        else:
            out += s[i]
            i += 1
    return out


def parse(line):
    d = {}
    for part in line.strip().split(" "):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = unesc(v)
        elif part:
            d[part] = ""
    return d


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- proteção contra anti-flood do servidor ---
# O TeamSpeak dá "pontos" a cada comando; o cliente que passa de um limite é bloqueado/banido por flood, mesmo sem
# falar nada. Os valores padrão do servidor: perde ~5 pontos/s, bloqueia por volta de 150. Aqui usamos um "balde":
# cada comando custa pontos, o balde esvazia 4 pontos/s e nunca deixamos passar de 90 (bem abaixo do limite).
BUCKET_MAX = 90.0
LEAK_PER_S = 4.0
COST_NET = 15.0        # comandos que realmente vão até o servidor (checam permissão / gravam)
NET_CMDS = ("permoverview", "servergroupsbyclientid", "servergroupaddclient", "servergroupdelclient")
# auth, clientnotifyregister, clientlist, whoami e servergrouplist são respondidos pelo próprio TeamSpeak local: não contam
_bucket = [0.0, time.time()]
_cooldown_until = [0.0]


def throttle(text=""):
    now = time.time()
    if now < _cooldown_until[0]:
        raise RuntimeError(f"Pausa de segurança: aguarde {int(_cooldown_until[0] - now) + 1}s (o servidor reclamou de excesso de comandos).")
    cost = COST_NET if text.split(" ")[0] in NET_CMDS else 0.0
    if cost == 0:
        time.sleep(0.05)
        return
    # esvazia o balde pelo tempo que passou
    _bucket[0] = max(0.0, _bucket[0] - (now - _bucket[1]) * LEAK_PER_S)
    _bucket[1] = now
    over = _bucket[0] + cost - BUCKET_MAX
    if over > 0:  # espera o balde esvaziar o suficiente
        time.sleep(over / LEAK_PER_S)
        _bucket[0] = max(0.0, _bucket[0] - (over / LEAK_PER_S) * LEAK_PER_S)
        _bucket[1] = time.time()
    _bucket[0] += cost


class TS:
    def __init__(self, apikey):
        self.s = socket.create_connection(("127.0.0.1", 25639), timeout=5)
        self.buf = b""
        self._read_until_prompt()
        self.cmd("auth apikey=" + apikey)
        for ev in ("notifyservergrouplist", "notifyservergroupsbyclientid", "notifypermoverview"):
            self.cmd(f"clientnotifyregister schandlerid=1 event={ev}")

    def _readline(self):
        while b"\n" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("conexão fechada")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip()

    def _drain(self):
        """Descarta qualquer linha sobrando de um comando anterior (a conexão é reaproveitada)."""
        import select
        self.buf = b""
        while select.select([self.s], [], [], 0)[0]:
            if not self.s.recv(65536):
                raise ConnectionError("conexão fechada")

    def _read_until_prompt(self):
        # banner do ClientQuery termina com "selected schandlerid=..."
        while True:
            if self._readline().startswith("selected schandlerid"):
                return

    def cmd(self, text, expect=None):
        """Envia um comando. Com `expect`, o resultado vem numa linha notify<expect>."""
        throttle(text)
        self._drain()
        self.s.sendall((text + "\n").encode("utf-8"))
        rows, got = [], []
        while True:
            line = self._readline()
            if not line:
                continue
            if line.startswith("notify"):
                if expect and line.startswith("notify" + expect + " "):
                    got.extend(parse(p) for p in line.split("|"))
                continue
            if line.startswith("error "):
                e = parse(line)
                if e.get("id") != "0":
                    if "flood" in (e.get("msg", "") + e.get("extra_msg", "")).lower() or e.get("id") in ("524", "3329"):
                        _cooldown_until[0] = time.time() + 90
                    raise RuntimeError(f"{e.get('msg', 'erro')} (id={e.get('id')}) {e.get('extra_msg', '')}".strip())
                return got if expect else rows
            rows.extend(parse(p) for p in line.split("|"))

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


_conn = [None]


def ts_session():
    if _conn[0] is None:
        cfg = load(CONFIG, {})
        if not cfg.get("apikey"):
            raise RuntimeError("API key não configurada")
        _conn[0] = TS(cfg["apikey"])
    return _conn[0]


_cache = {}


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


LEARN_TTL = 600  # segundos: depois disso o app tenta de novo (as permissões podem ter mudado)


def fresh_learned():
    now, out = time.time(), {}
    for sgid, v in load(LEARNED, {}).items():
        keep = {k: x for k, x in v.items() if k != "t" and now - v.get("t", {}).get(k, 0) < LEARN_TTL}
        if keep:
            out[sgid] = keep
    return out


def my_power(ts, clients, groups):
    """Seu poder de adicionar/remover membros, lido do servidor (2 comandos, guardado 10 min).
    IDs de permissão: 196 = i_group_member_add_power, 198 = i_group_member_remove_power;
    197/199 são os "necessários" de cada grupo (usados só para conferir que os IDs estão certos)."""
    def read():
        who = ts.cmd("whoami")[0]
        me = next((c for c in clients if c["clid"] == who["clid"]), None)
        if not me:
            return None
        rows = ts.cmd(f"permoverview cldbid={me['client_database_id']} cid={who['cid']} permid=0", "permoverview")
        rows = [r for r in rows if r.get("t") == "0" and r.get("n") != "1"]
        by = {}
        for r in rows:
            by.setdefault(int(r["p"]), []).append((r["id1"], int(r["v"])))
        # confere: o "necessário" do grupo (197) tem que bater com o n_member_addp que o servidor lista
        addp = {g["sgid"]: int(g.get("n_member_addp") or 0) for g in groups}
        ok = [v == addp.get(sg) for sg, v in by.get(197, []) if sg in addp]
        if not ok or not all(ok):
            return None  # não bate: melhor não bloquear nada do que bloquear errado
        top = lambda pid: max((v for _, v in by.get(pid, [])), default=None)
        return {"add": top(196), "rem": top(198), "cldbid": me["client_database_id"]}
    return cached("power", 600, read)


def api(path, body):
    if path == "/api/quit":  # usado pelo instalador para fechar o app antes de atualizar
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {"ok": True}
    if path == "/api/update/check":
        return updater.check(VERSION)
    if path == "/api/update/download":
        return updater.download(DATA, VERSION)
    if path == "/api/restart":
        threading.Timer(0.4, restart).start()
        return {"ok": True}
    if path == "/api/forget":
        save(LEARNED, {})
        return {"ok": True}
    if path == "/api/config":
        save(CONFIG, {"apikey": body.get("apikey", "").strip()})
        return {"ok": True}
    if path == "/api/presets":
        if "presets" in body:
            save(PRESETS, body["presets"])
        return {"presets": load(PRESETS, [])}

    with LOCK:
        ts = ts_session()
        try:
            if path == "/api/info":
                groups = cached("groups", 120, lambda: ts.cmd("servergrouplist", "servergrouplist"))
                groups = [g for g in groups if g.get("type") in ("1", None)]  # só grupos normais
                clients = cached("clients", 15, lambda: ts.cmd("clientlist"))
                clients = [c for c in clients if c.get("client_type") == "0"]
                if not clients:
                    _cache.clear()
                    raise RuntimeError("O TeamSpeak não está conectado a um servidor.")
                try:
                    power = my_power(ts, clients, groups)
                except RuntimeError as e:
                    power = None
                return {
                    "learned": fresh_learned(),
                    "power": power,
                    "groups": [{"sgid": g["sgid"], "name": g["name"], "sortid": int(g.get("sortid") or 0),
                                "addp": int(g.get("n_member_addp") or 0), "remp": int(g.get("n_member_removep") or 0)} for g in groups],
                    "clients": [{"clid": c["clid"], "cldbid": c["client_database_id"],
                                 "name": c["client_nickname"]} for c in clients],
                }
            if path == "/api/find":
                rows = ts.cmd("clientdbfind pattern=%" + esc(body["pattern"]) + "%")
                return {"clients": [{"cldbid": r["cldbid"], "name": r.get("client_nickname", "?")} for r in rows]}
            if path == "/api/member":
                rows = ts.cmd("servergroupsbyclientid cldbid=" + body["cldbid"], "servergroupsbyclientid")
                return {"sgids": [r["sgid"] for r in rows]}
            if path == "/api/canremove":
                # Teste sem efeito colateral: tenta remover de um ID que não existe. O servidor checa a permissão
                # ANTES de procurar o cliente, então "2568" = sem permissão; qualquer outro erro = tem permissão.
                def probe(sgid):
                    try:
                        ts.cmd(f"servergroupdelclient sgid={sgid} cldbid=2000000000")
                        return True
                    except RuntimeError as e:
                        if "Pausa de seguran" in str(e):
                            raise
                        if "id=2568" in str(e):
                            return False   # sem permissão (confirmado pelo servidor)
                        return None        # outro erro: não dá para afirmar nada (não trava nem libera)
                # a permissão é do grupo, não da pessoa: guarda 15 min para não repetir comandos
                out = {}
                for sgid in body.get("sgids", [])[:5]:   # no máximo 5 por chamada (não segura o painel)
                    v = cached("rem" + sgid, 900, lambda sg=sgid: probe(sg))
                    if v is None:
                        _cache.pop("rem" + sgid, None)
                    out[sgid] = v
                return {"can": out}
            if path == "/api/apply":
                cldbid, add, rem = body["cldbid"], body.get("add", []), body.get("remove", [])
                errors, learned, failed = [], load(LEARNED, {}), []
                power = _cache.get("power", (0, None))[1]
                addp = {g["sgid"]: int(g.get("n_member_addp") or 0) for g in (_cache.get("groups", (0, []))[1] or [])}
                for sgids, verb, key in ((add, "servergroupaddclient", "add"), (rem, "servergroupdelclient", "rem")):
                    for sgid in sgids:
                        entry = learned.setdefault(sgid, {})
                        entry.setdefault("t", {})
                        known_no = (key == "add" and power and power.get("add") is not None and addp.get(sgid, 0) > power["add"]) or \
                                   (key == "rem" and _cache.get("rem" + sgid, (0, None))[1] is False)
                        if known_no:
                            failed.append({"sgid": sgid, "action": key, "error": "insufficient client permissions (id=2568) [bloqueado antes de enviar]"})
                            errors.append(f"{key} {sgid}: sem permissão")
                            continue
                        try:
                            ts.cmd(f"{verb} sgid={sgid} cldbid={cldbid}")
                            entry[key] = True
                        except RuntimeError as e:
                            # só conta como "sem permissão" quando o servidor diz isso de forma explícita
                            if "id=2568" in str(e):
                                entry[key] = False
                            failed.append({"sgid": sgid, "action": key, "error": str(e)})
                            errors.append(f"{key} {sgid}: {e}")
                        entry["t"][key] = time.time()
                save(LEARNED, learned)
                _cache.pop("clients", None)   # permissões não mudam ao aplicar: mantém o cache para não repetir comandos
                return {"ok": not errors, "errors": errors, "failed": failed, "learned": fresh_learned()}
        except (OSError, ConnectionError):
            _conn[0] = None  # reconecta na próxima
            _cache.clear()
            raise
    raise RuntimeError("rota desconhecida")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype="application/json"):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlparse(self.path).path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if urlparse(self.path).path == "/api/ping":
            last_ping[0] = time.time()
            return self._send(200, {"ok": True})
        if urlparse(self.path).path == "/icon.png":
            with open(os.path.join(HERE, "icon.png"), "rb") as f:
                return self._send(200, f.read(), "image/png")
        if urlparse(self.path).path == "/skin-frost.jpg":
            with open(os.path.join(HERE, "skin-frost.jpg"), "rb") as f:
                return self._send(200, f.read(), "image/jpeg")
        if urlparse(self.path).path == "/api/status":
            return self._send(200, {"hasKey": bool(load(CONFIG, {}).get("apikey")), "version": VERSION})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # proteção: só aceita chamadas feitas pela própria página local (impede que um site aberto no navegador
        # mande comandos para o painel): Host local, Origin (se houver) local e cabeçalho próprio obrigatório
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self._send(403, {"error": "host inválido"})
        origin = self.headers.get("Origin")
        if origin and origin not in (URL, "http://localhost:8765"):
            return self._send(403, {"error": "origem não permitida"})
        if self.headers.get("X-Requested-With") != "gts3":
            return self._send(403, {"error": "cabeçalho ausente"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, api(urlparse(self.path).path, body))
        except ConnectionRefusedError:
            self._send(500, {"error": "TeamSpeak não está aberto (ou ClientQuery desativado)."})
        except Exception as e:
            self._send(500, {"error": str(e)})


def restart():
    """Reinicia o próprio servidor (pega a versão baixada em <dados>/current)."""
    os.environ["GRUPOS_BOOT"] = "0"
    os.environ["GRUPOS_NO_BROWSER"] = "1"  # a janela já está aberta; ela recarrega sozinha
    if WIN:
        # no Windows o execv não coloca aspas em caminhos com espaço ("Grupos TS3"): abre um novo processo e sai
        subprocess.Popen([sys.executable] + sys.argv, creationflags=0x08000000)  # CREATE_NO_WINDOW
        os._exit(0)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def open_window():
    """Windows: abre numa janela própria (Edge/Chrome em modo app, sem barra de navegador)."""
    if WIN:
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        cands = [os.path.join(p, *rel) for p in pf if p for rel in
                 (("Microsoft", "Edge", "Application", "msedge.exe"), ("Google", "Chrome", "Application", "chrome.exe"))]
        for exe in cands:
            if os.path.exists(exe):
                subprocess.Popen([exe, "--app=" + URL, "--window-size=1120,760", "--no-first-run",
                                  "--user-data-dir=" + os.path.join(DATA, "janela")])
                return
    webbrowser.open(URL)


def watchdog():
    """Fecha o servidor quando a janela do app é fechada (a página manda um 'ping' a cada 3 s)."""
    start = time.time()
    while True:
        time.sleep(3)
        if last_ping[0] and time.time() - last_ping[0] > 15:
            os._exit(0)
        if not last_ping[0] and time.time() - start > 120:
            os._exit(0)


if __name__ == "__main__":
    srv = None
    for _ in range(20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
            break
        except OSError:
            time.sleep(0.4)
    if srv is None:  # já está rodando: só abre outra janela
        if WIN:
            open_window()
        sys.exit(0)
    print("Painel em " + URL + "  (Ctrl+C para sair)")
    if WIN:
        threading.Thread(target=watchdog, daemon=True).start()
    if not os.environ.get("GRUPOS_NO_BROWSER"):
        threading.Timer(0.5, open_window).start()
    srv.serve_forever()
