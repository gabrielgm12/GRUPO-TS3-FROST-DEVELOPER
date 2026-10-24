"""Atualização automática pelo GitHub (sem token: usa os arquivos públicos do repositório).

Como funciona
  1. O repositório tem um `manifest.json` (versão + SHA-256 de cada arquivo do app).
  2. O app lê o manifest; se a versão for maior que a instalada, baixa os arquivos novos,
     confere o SHA-256 de cada um e guarda em  <dados>/current/.
  3. Na próxima abertura (ou ao clicar em "Reiniciar") o app passa a rodar a partir de <dados>/current/.
Nada é gravado dentro da pasta do app instalado, então funciona no Mac e no Windows sem permissão extra.
"""
import hashlib, json, os, shutil, urllib.request

REPO = "gabrielgm12/GRUPO-TS3-FROST-DEVELOPER"
BRANCH = "main"
RAW = os.environ.get("GRUPOS_RAW") or f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
ALLOWED = {"server.py", "updater.py", "index.html", "skin-frost.jpg", "icon.png", "version.txt"}
HEADERS = {"User-Agent": "GruposTS3-Updater"}


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


def _get(name, timeout=15):
    req = urllib.request.Request(RAW + name, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(running_version):
    """Compara a versão que está rodando com a do GitHub."""
    try:
        m = json.loads(_get("manifest.json", 8).decode("utf-8"))
    except Exception as e:
        return {"ok": False, "current": running_version, "error": f"sem acesso ao GitHub ({e.__class__.__name__})"}
    latest = str(m.get("version", "0"))
    return {"ok": True, "current": running_version, "latest": latest,
            "available": vt(latest) > vt(running_version), "notes": m.get("notes", "")}


def download(data_dir, running_version):
    """Baixa a versão nova para <dados>/current (só se for mais nova que a que está rodando)."""
    m = json.loads(_get("manifest.json").decode("utf-8"))
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
            blob = _get(name, 60)
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
        cur, old = os.path.join(data_dir, "current"), os.path.join(data_dir, "current.old")
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(cur):
            os.replace(cur, old)
        os.replace(stage, cur)
        shutil.rmtree(old, ignore_errors=True)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"ok": True, "updated": True, "latest": latest, "notes": m.get("notes", "")}
