"""Atualização automática pelo GitHub (sem token: usa os arquivos públicos do repositório).

Como funciona
  1. O repositório tem um `manifest.json` (versão + SHA-256 de cada arquivo do app).
  2. O app lê o manifest; se a versão for maior que a instalada, baixa os arquivos novos,
     confere o SHA-256 de cada um e guarda em  <dados>/current/.
  3. Na próxima abertura (ou ao clicar em "Reiniciar") o app passa a rodar a partir de <dados>/current/.
Nada é gravado dentro da pasta do app instalado, então funciona no Mac e no Windows sem permissão extra.
"""
import hashlib, json, os, re, shutil, urllib.request

REPO = "gabrielgm12/GRUPO-TS3-FROST-DEVELOPER"
BRANCH = "main"
RAW = os.environ.get("GRUPOS_RAW") or f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
ALLOWED = {"server.py", "updater.py", "index.html", "skin-frost.jpg", "icon.png", "version.txt"}
HEADERS = {"User-Agent": "GruposTS3-Updater"}


def log(data_dir, msg):
    """Anota o que deu errado em <dados>/atualizacao.log (aparece no botão Diagnóstico)."""
    try:
        import time
        with open(os.path.join(data_dir, "atualizacao.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _trocar(src, dst):
    """Troca um arquivo com tentativas (no Windows antivírus/janela podem segurar o arquivo por instantes)."""
    import time
    ultimo = None
    for _ in range(8):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            ultimo = e
            time.sleep(0.4)
    raise ultimo


def _instalar(stage, cur, nomes):
    """Copia os arquivos novos para <dados>/current ARQUIVO A ARQUIVO (renomear a pasta inteira falha no Windows se
    algo estiver aberto lá dentro). Se algum falhar, devolve os antigos. version.txt vai por último."""
    os.makedirs(cur, exist_ok=True)
    ordem = [n for n in nomes if n != "version.txt"] + (["version.txt"] if "version.txt" in nomes else [])
    antigos, feitos = {}, []
    try:
        for n in ordem:
            dst = os.path.join(cur, n)
            if os.path.exists(dst):
                with open(dst, "rb") as f:
                    antigos[n] = f.read()
            tmp = dst + ".novo"
            shutil.copyfile(os.path.join(stage, n), tmp)
            _trocar(tmp, dst)
            feitos.append(n)
    except Exception:
        for n in feitos:   # desfaz: volta o que já tinha sido trocado
            try:
                if n in antigos:
                    with open(os.path.join(cur, n), "wb") as f:
                        f.write(antigos[n])
                else:
                    os.remove(os.path.join(cur, n))
            except OSError:
                pass
        raise


def vt(v):
    out = []
    for p in str(v).strip().lstrip("v").split("."):
        out.append(int("".join(c for c in p if c.isdigit()) or 0))
    return tuple(out)


def read_version(folder):
    try:
        with open(os.path.join(folder, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0"


def _base():
    """(endereço dos arquivos, de onde veio). Usa o commit mais recente (SHA) em vez da branch: o GitHub guarda a branch
    em cache por ~5 min e misturava manifest novo com arquivos velhos (checksum não confere -> a atualização nunca instalava).
    Ordem: API do GitHub (60 consultas/h por internet) -> feed do repositório (sem esse limite) -> branch (pode estar em cache)."""
    if os.environ.get("GRUPOS_RAW"):
        return RAW, "teste"
    erros = []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}",
                                     headers={**HEADERS, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            sha = json.loads(r.read().decode("utf-8")).get("sha", "")
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return f"https://raw.githubusercontent.com/{REPO}/{sha}/", "commit " + sha[:7]
    except Exception as e:
        erros.append("API " + (str(getattr(e, "code", "")) or e.__class__.__name__))
    try:
        req = urllib.request.Request(f"https://github.com/{REPO}/commits/{BRANCH}.atom", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            m = re.search(r"Grit::Commit/([0-9a-f]{40})", r.read(200000).decode("utf-8", "replace"))
        if m:
            return f"https://raw.githubusercontent.com/{REPO}/{m.group(1)}/", "commit " + m.group(1)[:7]
    except Exception as e:
        erros.append("feed " + (str(getattr(e, "code", "")) or e.__class__.__name__))
    return RAW, "cache da branch (" + ", ".join(erros) + ")"


def _get(name, timeout=15, base=None):
    req = urllib.request.Request((base or RAW) + name, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(running_version, data_dir=None):
    """Compara a versão que está rodando com a do GitHub."""
    base, fonte = _base()
    try:
        m = json.loads(_get("manifest.json", 8, base).decode("utf-8"))
    except Exception as e:
        if data_dir:
            log(data_dir, f"checagem falhou ({fonte}): {e.__class__.__name__}: {e}")
        return {"ok": False, "current": running_version, "error": f"sem acesso ao GitHub ({e.__class__.__name__}: {e})"}
    latest = str(m.get("version", "0"))
    return {"ok": True, "current": running_version, "latest": latest, "source": fonte,
            "available": vt(latest) > vt(running_version), "notes": m.get("notes", "")}


def download(data_dir, running_version):
    """Baixa a versão nova para <dados>/current (só se for mais nova que a que está rodando)."""
    base, fonte = _base()   # manifest e arquivos do MESMO commit
    m = json.loads(_get("manifest.json", 15, base).decode("utf-8"))
    latest = str(m["version"])
    if vt(latest) <= vt(running_version):
        return {"ok": True, "updated": False, "latest": latest}
    files = m["files"]
    stage = os.path.join(data_dir, "current.new")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    try:
        for name, sha in files.items():
            if name not in ALLOWED or "/" in name or "\\" in name:
                raise ValueError(f"arquivo não permitido no manifest: {name}")
            blob = _get(name, 60, base)
            if hashlib.sha256(blob).hexdigest() != sha.lower():
                raise ValueError(f"checksum não confere: {name}")
            with open(os.path.join(stage, name), "wb") as f:
                f.write(blob)
        for need in ("server.py", "updater.py", "index.html", "version.txt"):
            if not os.path.exists(os.path.join(stage, need)):
                raise ValueError(f"pacote incompleto: falta {need}")
        # o servidor novo precisa ao menos compilar antes de ser aceito
        for py in ("server.py", "updater.py"):
            with open(os.path.join(stage, py), encoding="utf-8") as f:
                compile(f.read(), py, "exec")
        cur = os.path.join(data_dir, "current")
        _instalar(stage, cur, list(files))
        shutil.rmtree(stage, ignore_errors=True)
    except Exception as e:
        log(data_dir, f"falha ao instalar {latest}: {e.__class__.__name__}: {e}")
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"ok": True, "updated": True, "latest": latest, "notes": m.get("notes", "")}
