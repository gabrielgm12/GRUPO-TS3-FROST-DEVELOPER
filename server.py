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
bye = [0.0]   # a página avisa quando é fechada (pagehide)
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
SERVER_FILE = os.path.join(DATA, "servidor.json")  # nome do servidor escolhido
_srvkey = ["x"]  # identifica o servidor escolhido (as recusas aprendidas valem só para ele)
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
NET_CMDS = ("permoverview", "servergroupsbyclientid", "servergroupaddclient", "servergroupdelclient", "servergroupclientlist")
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
        self.sch = "1"
        self.reg = set()
        self._read_until_prompt()
        self.cmd("auth apikey=" + apikey)
        self.register()

    def register(self):
        # registrar de novo um evento já registrado faz o TS3 não responder: só uma vez por servidor
        if self.sch in self.reg:
            return
        self.reg.add(self.sch)
        for ev in ("notifyservergrouplist", "notifyservergroupsbyclientid", "notifypermoverview", "notifyservergroupclientlist"):
            self.cmd(f"clientnotifyregister schandlerid={self.sch} event={ev}")

    def use(self, sch):
        """Escolhe em qual servidor (aba do TeamSpeak) os comandos valem."""
        self.cmd(f"use schandlerid={sch}")
        self.sch = str(sch)
        self.register()

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
            ln = self._readline()
            if ln.startswith("selected schandlerid"):
                self.sch = ln.split("=", 1)[1].strip() or "1"
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
                    ex = RuntimeError(f"{e.get('msg', 'erro')} (id={e.get('id')}){' permid=' + e['failed_permid'] if e.get('failed_permid') else ''} {e.get('extra_msg', '')}".strip())
                    ex.raw = line
                    raise ex
                return got if expect else rows
            rows.extend(parse(p) for p in line.split("|"))

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


_conn = [None]
_sel = [None]   # servidor (schandlerid) escolhido no painel


def ts_session():
    if _conn[0] is None:
        cfg = load(CONFIG, {})
        if not cfg.get("apikey"):
            raise RuntimeError("API key não configurada")
        _conn[0] = TS(cfg["apikey"])
        if _sel[0]:
            try:
                _conn[0].use(_sel[0])
            except RuntimeError:
                _sel[0] = None
        set_srvkey(_conn[0])
    return _conn[0]


_cache = {}
_seen = {}   # cldbid -> (quando, grupos) lidos há pouco


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val is not None:
        _cache[key] = (time.time(), val)
    return val


LEARN_TTL = 365 * 24 * 3600  # fica salvo no PC; o botão 'Reverificar' refaz quando a pessoa for promovida


def LEARNED_path():
    return os.path.join(DATA, f"perms-{_srvkey[0]}.json")  # {sgid: {add, rem, t}} aprendido nas tentativas


def set_srvkey(ts):
    import hashlib
    try:
        nome = (ts.cmd("servervariable virtualserver_name") or [{}])[0].get("virtualserver_name") or ""
    except RuntimeError:
        nome = ""
    try:   # as permissões são de cada CONTA: quem usa outra conta no mesmo PC não herda o resultado
        who = ts.cmd("whoami")[0]
        eu = next((c["client_database_id"] for c in ts.cmd("clientlist") if c.get("clid") == who.get("clid")), "")
    except (RuntimeError, IndexError, KeyError):
        eu = ""
    _srvkey[0] = hashlib.sha1((nome + "|" + eu).encode("utf-8")).hexdigest()[:10]


def fresh_learned():
    now, out = time.time(), {}
    for sgid, v in load(LEARNED_path(), {}).items():
        keep = {k: x for k, x in v.items() if k != "t" and now - v.get("t", {}).get(k, 0) < LEARN_TTL}
        if keep:
            out[sgid] = keep
    return out


def my_power(ts, clients, groups):
    """Seu poder de adicionar/remover membros, lido do servidor pelo NOME da permissão (os IDs numéricos mudam de
    servidor para servidor). Permissão do próprio cliente (t=1) vale mais que a dos grupos (t=0); entre grupos vale o maior.
    Sem nenhuma linha = poder 0. Se a leitura falhar devolve None (e não guarda no cache)."""
    def read():
        who = ts.cmd("whoami")[0]
        me = next((c for c in clients if c["clid"] == who["clid"]), None)
        if not me:
            return None

        def val(name):
            rows = ts.cmd(f"permoverview cldbid={me['client_database_id']} cid={who['cid']} permsid={name}", "permoverview")
            rows = [r for r in rows if r.get("v") not in (None, "")]
            own = [int(r["v"]) for r in rows if r.get("t") == "1"]
            if own:
                return max(own)
            grp = [int(r["v"]) for r in rows if r.get("t") == "0" and r.get("n") != "1"]
            return max(grp, default=0)
        out = {"add": val("i_group_member_add_power"), "rem": val("i_group_member_remove_power"),
               "cldbid": me["client_database_id"], "cpm": None}
        try:
            out["cpm"] = val("i_client_permission_modify_power")   # poder sobre PESSOAS (exigido além do poder sobre a tag)
        except RuntimeError:
            pass
        return out
    return cached("power", 600, read)


def api(path, body):
    if path == "/api/quit":  # usado pelo instalador para fechar o app antes de atualizar
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {"ok": True}
    if path == "/api/update/check":
        return updater.check(VERSION, DATA)
    if path == "/api/diag/update":
        L = [f"app v{VERSION} | {sys.platform} | python {sys.version.split()[0]} | {sys.executable}",
             f"pasta do app: {HERE}", f"pasta de dados: {DATA}"]
        cur = os.path.join(DATA, "current")
        L.append(f"pasta 'current': {'v' + updater.read_version(cur) + ' ' + str(sorted(os.listdir(cur))) if os.path.isdir(cur) else 'não existe'}")
        L.append(f"versão instalada (pacote): v{updater.read_version(os.path.dirname(os.path.abspath(updater.__file__)))} | rodando de: {HERE}")
        try:
            c = updater.check(VERSION, DATA)
            L.append(f"checagem: {c}")
        except Exception as e:
            L.append(f"checagem lançou erro: {e.__class__.__name__}: {e}")
        try:
            with open(os.path.join(DATA, "atualizacao.log"), encoding="utf-8") as f:
                L.append("atualizacao.log (últimas linhas):\n" + "".join(f.readlines()[-8:]).rstrip())
        except OSError:
            L.append("atualizacao.log: vazio (nenhuma falha registrada)")
        return {"report": "\n".join(L)}
    if path == "/api/update/download":
        return updater.download(DATA, VERSION)
    if path == "/api/restart":
        threading.Timer(0.4, restart).start()
        return {"ok": True}
    if path == "/api/forget":
        _cache.clear()      # só a memória temporária; as permissões verificadas continuam salvas
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
                perr = ""
                try:
                    power = my_power(ts, clients, groups)
                    if power is None:
                        perr = "não achei você na lista de clientes"
                except RuntimeError as e:
                    power, perr = None, str(e)
                return {
                    "powerErr": perr,
                    "learned": fresh_learned(),
                    "power": power,
                    "groups": [{"sgid": g["sgid"], "name": g["name"], "sortid": int(g.get("sortid") or 0),
                                "addp": int(g.get("n_member_addp") or 0), "remp": int(g.get("n_member_removep") or 0)} for g in groups],
                    "clients": [{"clid": c["clid"], "cldbid": c["client_database_id"],
                                 "name": c["client_nickname"]} for c in clients],
                }
            if path == "/api/servers":
                out = []
                for h in ts.cmd("serverconnectionhandlerlist"):
                    sch = h.get("schandlerid")
                    if not sch:
                        continue
                    try:
                        ts.use(sch)
                        nome = (ts.cmd("servervariable virtualserver_name") or [{}])[0].get("virtualserver_name") or ""
                    except RuntimeError:
                        continue  # aba sem conexão com servidor
                    if nome:
                        out.append({"sch": sch, "name": nome})
                saved = load(SERVER_FILE, {}).get("name")
                pick = next((o for o in out if o["sch"] == _sel[0]), None) or next((o for o in out if o["name"] == saved), None)
                asked = pick is None and len(out) > 1   # vários servidores e nenhum escolhido ainda
                pick = pick or (out[0] if out else None)
                if pick:
                    _sel[0] = pick["sch"]
                    ts.use(pick["sch"])
                    set_srvkey(ts)
                return {"servers": out, "selected": _sel[0], "choose": asked}
            if path == "/api/server/select":
                sch = str(body.get("sch", ""))
                if not sch.isdigit():
                    raise RuntimeError("dados inválidos")
                ts.use(sch)
                _sel[0] = sch
                nome = (ts.cmd("servervariable virtualserver_name") or [{}])[0].get("virtualserver_name") or ""
                save(SERVER_FILE, {"name": nome})
                _cache.clear()
                set_srvkey(ts)
                return {"ok": True}
            if path == "/api/find":
                rows = ts.cmd("clientdbfind pattern=%" + esc(body["pattern"]) + "%")
                return {"clients": [{"cldbid": r["cldbid"], "name": r.get("client_nickname", "?")} for r in rows]}
            if path == "/api/member":
                if not str(body.get("cldbid", "")).isdigit():
                    raise RuntimeError("dados inválidos")
                rows = ts.cmd("servergroupsbyclientid cldbid=" + body["cldbid"], "servergroupsbyclientid")
                _seen[str(body["cldbid"])] = (time.time(), {r["sgid"] for r in rows})
                return {"sgids": [r["sgid"] for r in rows]}
            if path == "/api/canremove":
                # descontinuado: o teste com ID inexistente dava falso "sem permissão". A regra de poder
                # (seu poder x o que a tag exige, vindo do servidor) é usada no lugar, sem comandos extras.
                return {"can": {sgid: None for sgid in body.get("sgids", [])}}
            if path == "/api/diag":
                # relatório para diagnóstico (só leitura + testes sem efeito). Texto simples para copiar e colar.
                cldbid = str(body.get("cldbid", ""))
                if not cldbid.isdigit():
                    raise RuntimeError("Escolha uma pessoa na lista antes de rodar o diagnóstico.")
                have = {r["sgid"] for r in ts.cmd("servergroupsbyclientid cldbid=" + cldbid, "servergroupsbyclientid")}  # sempre fresco
                L = [f"app v{VERSION} | servidor schandlerid={ts.sch} chave={_srvkey[0]}"]
                glist = cached("groups", 120, lambda: ts.cmd("servergrouplist", "servergrouplist"))
                gn = [g for g in glist if g.get("type") in ("1", None)]
                L.append(f"grupos: {len(glist)} no total, {len(gn)} normais; campos do 1º: {sorted(glist[0].keys()) if glist else '-'}")
                ap = sorted({int(g.get('n_member_addp') or 0) for g in gn}); rp = sorted({int(g.get('n_member_removep') or 0) for g in gn})
                L.append(f"níveis exigidos p/ adicionar: {ap[:15]}{'…' if len(ap) > 15 else ''} | p/ remover: {rp[:15]}{'…' if len(rp) > 15 else ''}")
                clist = [c for c in cached("clients", 15, lambda: ts.cmd("clientlist")) if c.get("client_type") == "0"]
                try:
                    L.append(f"poder lido do servidor: {my_power(ts, clist, gn)}")
                except RuntimeError as e:
                    L.append(f"leitura do poder FALHOU: {e}")
                nm = lambda g: g.get("name", "?")[:28]
                L.append(f"pessoa escolhida (cldbid {cldbid}) está em {len(have)} grupo(s): {sorted(have)[:12]}")

                def tentar(verb, g, alvo, rotulo):
                    try:
                        ts.cmd(f"{verb} sgid={g['sgid']} cldbid={alvo}")
                        r = "SEM ERRO (!)"
                    except RuntimeError as e:
                        r = getattr(e, "raw", str(e))
                    L.append(f"{rotulo} | grupo {g['sgid']} '{nm(g)}' | alvo {alvo} -> {r}")

                def amostra(pool, field):
                    por_nivel = {}
                    for g in sorted(pool, key=lambda g: int(g.get(field) or 0)):
                        por_nivel.setdefault(int(g.get(field) or 0), g)
                    ks = sorted(por_nivel)
                    pick = ks if len(ks) <= 8 else [ks[i * (len(ks) - 1) // 7] for i in range(8)]
                    return [(k, por_nivel[k]) for k in pick]

                for k, g in amostra([g for g in gn if int(g.get("n_member_removep") or 0) > 0 and g["sgid"] not in have], "n_member_removep"):
                    tentar("servergroupdelclient", g, cldbid, f"REMOVER nivel {k}")
                for k, g in amostra([g for g in gn if int(g.get("n_member_addp") or 0) > 0 and g["sgid"] in have], "n_member_addp"):
                    tentar("servergroupaddclient", g, cldbid, f"ADICIONAR(ja esta) nivel {k}")
                feitos = 0
                for k, g in amostra([g for g in gn if int(g.get("n_member_addp") or 0) > 0 and g["sgid"] not in have], "n_member_addp"):
                    if feitos >= 4:
                        break
                    try:
                        mem = ts.cmd(f"servergroupclientlist sgid={g['sgid']}", "servergroupclientlist")
                    except RuntimeError as e:
                        L.append(f"lista de membros do grupo {g['sgid']} -> {getattr(e, 'raw', e)}")
                        continue
                    mem = [m["cldbid"] for m in mem if m.get("cldbid", "").isdigit()]
                    if mem:
                        feitos += 1
                        tentar("servergroupaddclient", g, mem[0], f"ADICIONAR(membro) nivel {k}")
                return {"report": "\n".join(L)}
            if path == "/api/recheck":
                # pessoa foi promovida (ou rebaixada): esquece o que foi verificado para testar de novo
                todas = bool(body.get("all"))
                learned = load(LEARNED_path(), {})
                for sg in list(learned):
                    v = learned[sg]
                    for k in ("add", "rem"):
                        if k in v and (todas or v[k] is False):
                            v.pop(k, None)
                            v.get("t", {}).pop(k, None)
                    if not any(k in v for k in ("add", "rem")):
                        del learned[sg]
                save(LEARNED_path(), learned)
                for k in [k for k in _cache if k in ("power", "groups", "clients") or k.startswith(("target:", "mine:", "members:"))]:
                    _cache.pop(k, None)
                return {"learned": fresh_learned()}
            if path == "/api/target":
                cldbid = str(body.get("cldbid", ""))
                if not cldbid.isdigit():
                    raise RuntimeError("dados inválidos")
                def read():
                    who = ts.cmd("whoami")[0]
                    rows = ts.cmd(f"permoverview cldbid={cldbid} cid={who['cid']} permsid=i_client_needed_permission_modify_power", "permoverview")
                    own = [int(r["v"]) for r in rows if r.get("t") == "1" and r.get("v")]
                    grp = [int(r["v"]) for r in rows if r.get("t") == "0" and r.get("n") != "1" and r.get("v")]
                    return {"need": max(own) if own else max(grp, default=0)}
                try:
                    return cached("target:" + cldbid, 120, read)
                except RuntimeError:
                    return {"need": None}   # o servidor não deixa ver as permissões dela
            if path == "/api/can":
                # Teste de UMA tag, sem efeito em ninguém (usado quando o servidor não deixa ler as permissões).
                # Os grupos de quem está online vêm de `clientlist -groups` (local, sem custo de flood e sem exigir permissão).
                #  adicionar: alguém online que JÁ tem a tag; tenta adicionar de novo ("já é membro" = permitido)
                #  remover:   alguém online que NÃO tem a tag; tenta remover ("não é membro" = permitido)
                # 2568 pode ser por causa da TAG (seu poder de adicionar/remover) ou da PESSOA usada no teste (ela é protegida,
                # ex.: Admin). O servidor diz qual com failed_permid: só vale como "sem permissão para a tag" se o id for o do
                # poder de adicionar/remover (aprendido quando o alvo é você mesmo, ou repetido em duas pessoas diferentes).
                import re
                sgid, action = str(body.get("sgid", "")), body.get("action")
                if not sgid.isdigit() or action not in ("add", "rem"):
                    raise RuntimeError("dados inválidos")
                known = fresh_learned().get(sgid, {})
                if action in known:
                    return {"ok": known[action], "why": "", "learned": fresh_learned()}
                ids_path = os.path.join(DATA, f"permids-{_srvkey[0]}.json")
                ids = load(ids_path, {})
                try:
                    me_clid = ts.cmd("whoami")[0]["clid"]
                except (RuntimeError, IndexError, KeyError):
                    me_clid = None
                online = [c for c in ts.cmd("clientlist -groups") if c.get("client_type") == "0" and c.get("client_database_id")]  # sempre fresco
                has_g = lambda c: sgid in (c.get("client_servergroups") or "").split(",")
                prot = {g["sgid"]: int(g.get("n_modifyp") or 0) for g in cached("groups", 120, lambda: ts.cmd("servergrouplist", "servergrouplist"))}
                protecao = lambda c: max([prot.get(x, 0) for x in (c.get("client_servergroups") or "").split(",") if x] or [0])
                pool = [c for c in online if has_g(c) == (action == "add")]
                pool.sort(key=lambda c: (c["clid"] != me_clid, protecao(c)))   # você primeiro, depois as pessoas menos protegidas
                verb = "servergroupaddclient" if action == "add" else "servergroupdelclient"
                verdict, why, denials = None, "", []
                if not pool:
                    why = "ninguém online tem esta tag para servir de teste" if action == "add" else "todos online já têm esta tag"
                for c in pool[:2]:
                    try:
                        ts.cmd(f"{verb} sgid={sgid} cldbid={c['client_database_id']}")
                        verdict = True
                        break
                    except RuntimeError as e:
                        m = str(e)
                        pid = (re.search(r"permid=(\d+)", m) or [None, None])[1]
                        if "id=2568" in m:
                            denials.append((c["clid"] == me_clid, pid))
                        elif any(f"id={x})" in m or f"id={x} " in m for x in ("531", "532", "2561", "2563")):
                            verdict = True
                            break
                        else:
                            why = m
                            break
                if verdict is None and denials:
                    sure = set(ids.get(action, []))
                    first_self, first_pid = denials[0]
                    if first_self and first_pid:
                        sure.add(first_pid)            # negou até para você mesmo: este id é o do poder de adicionar/remover
                    if len(denials) == 2 and denials[0][1] and denials[0][1] == denials[1][1]:
                        sure.add(denials[0][1])        # mesma permissão negou em duas pessoas diferentes
                    ids[action] = sorted(sure)
                    save(ids_path, ids)
                    if any(p in sure for _, p in denials):
                        verdict = False
                    else:
                        why = "negado por causa da pessoa usada no teste (protegida), não da tag"
                if verdict is not None:
                    learned = load(LEARNED_path(), {})
                    e = learned.setdefault(sgid, {})
                    e.setdefault("t", {})
                    e[action] = verdict
                    e["t"][action] = time.time()
                    save(LEARNED_path(), learned)
                return {"ok": verdict, "why": why, "learned": fresh_learned()}
            if path == "/api/probe":
                # Servidor não deixa ler as permissões: descobre o poder com comandos SEM efeito, por busca binária.
                #  remover: grupo em que a pessoa NÃO está   -> 2563 (permitido) ou 2568 (sem permissão)
                #  adicionar: grupo em que a pessoa JÁ está  -> 2561 (permitido) ou 2568 (sem permissão)
                cldbid = str(body.get("cldbid", ""))
                if not cldbid.isdigit():
                    raise RuntimeError("dados inválidos")
                seen = _seen.get(cldbid)
                if seen and time.time() - seen[0] < 20:    # acabou de ser lido ao escolher a pessoa
                    have = set(seen[1])
                else:
                    have = {r["sgid"] for r in ts.cmd("servergroupsbyclientid cldbid=" + cldbid, "servergroupsbyclientid")}
                glist = cached("groups", 120, lambda: ts.cmd("servergrouplist", "servergrouplist"))
                glist = [g for g in glist if g.get("type") in ("1", None)]
                learned = load(LEARNED_path(), {})
                budget, lists = 8, 4
                for key, verb, field, okid in (("rem", "servergroupdelclient", "n_member_removep", "2563"),
                                               ("add", "servergroupaddclient", "n_member_addp", "2561")):
                    need = lambda g: int(g.get(field) or 0)
                    # remover: só grupos em que a pessoa NÃO está. adicionar: qualquer grupo, usando um membro dele como alvo
                    pool = [g for g in glist if need(g) > 0 and (key == "add" or g["sgid"] not in have)]
                    for _ in range(6):
                        if budget <= 0 or not pool:
                            break
                        byid = {g["sgid"]: g for g in glist}
                        denied = [need(byid[i]) for i, v in learned.items() if i in byid and v.get(key) is False and need(byid[i]) > 0]
                        allowed = [need(byid[i]) for i, v in learned.items() if i in byid and v.get(key) is True]
                        lo, hi = min(denied, default=10**9), max(allowed, default=0)
                        cand = [g for g in pool if hi < need(g) < lo]
                        if not cand:
                            break
                        levels = sorted({need(g) for g in cand})
                        g = next(x for x in cand if need(x) == levels[len(levels) // 2])
                        target = cldbid
                        if key == "add" and g["sgid"] not in have:
                            pool.remove(g)
                            if lists <= 0:
                                continue
                            lists -= 1
                            try:
                                mem = cached("members:" + g["sgid"], 300, lambda: ts.cmd(f"servergroupclientlist sgid={g['sgid']}", "servergroupclientlist"))
                            except RuntimeError:
                                continue
                            mem = [m["cldbid"] for m in mem if m.get("cldbid", "").isdigit()]
                            if not mem:
                                continue
                            target = mem[0]
                        else:
                            pool.remove(g)
                        budget -= 1
                        try:
                            ts.cmd(f"{verb} sgid={g['sgid']} cldbid={target}")
                            verdict = True
                        except RuntimeError as e:
                            m = str(e)
                            verdict = False if "id=2568" in m else True if f"id={okid}" in m else None
                        if verdict is not None:
                            e = learned.setdefault(g["sgid"], {})
                            e.setdefault("t", {})
                            e[key] = verdict
                            e["t"][key] = time.time()
                save(LEARNED_path(), learned)
                return {"learned": fresh_learned()}
            if path == "/api/apply":
                cldbid, add, rem = str(body["cldbid"]), body.get("add", []), body.get("remove", [])
                if not cldbid.isdigit() or not all(str(x).isdigit() for x in list(add) + list(rem)):
                    raise RuntimeError("dados inválidos")
                add, rem = [str(x) for x in add], [str(x) for x in rem]
                errors, learned, failed = [], load(LEARNED_path(), {}), []
                glist = cached("groups", 120, lambda: ts.cmd("servergrouplist", "servergrouplist"))
                glist = [g for g in glist if g.get("type") in ("1", None)]
                clist = [c for c in cached("clients", 15, lambda: ts.cmd("clientlist")) if c.get("client_type") == "0"]
                try:
                    power = my_power(ts, clist, glist)
                except RuntimeError:
                    power = None
                addp = {g["sgid"]: int(g.get("n_member_addp") or 0) for g in glist}
                remp = {g["sgid"]: int(g.get("n_member_removep") or 0) for g in glist}
                for sgids, verb, key in ((add, "servergroupaddclient", "add"), (rem, "servergroupdelclient", "rem")):
                    for sgid in sgids:
                        entry = learned.setdefault(sgid, {})
                        entry.setdefault("t", {})
                        known_no = (key == "add" and power and power.get("add") is not None and addp.get(sgid, 0) > power["add"]) or \
                                   (key == "rem" and power and power.get("rem") is not None and remp.get(sgid, 0) > power["rem"])
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
                save(LEARNED_path(), learned)
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
        if urlparse(self.path).path == "/api/bye":   # janela fechando (ou recarregando: o próximo ping cancela)
            bye[0] = time.time()
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
        last_ping[0] = time.time()
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
    """Fecha o servidor quando a janela do app é fechada. O navegador desacelera os timers de janelas minimizadas/em
    segundo plano (1 ping por minuto), então só a falta de ping NÃO derruba o servidor rápido (3 min); quem fecha
    rápido é o aviso 'bye' da página, que um novo ping (recarregar) cancela."""
    start = time.time()
    while True:
        time.sleep(3)
        now = time.time()
        if last_ping[0] and now - last_ping[0] > 180:
            os._exit(0)
        if bye[0] and last_ping[0] < bye[0] and now - bye[0] > 8:
            os._exit(0)
        if not last_ping[0] and now - start > 120:
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
    if WIN or os.environ.get("GRUPOS_TESTE_WATCHDOG"):
        threading.Thread(target=watchdog, daemon=True).start()
    if not os.environ.get("GRUPOS_NO_BROWSER"):
        threading.Timer(0.5, open_window).start()
    srv.serve_forever()
