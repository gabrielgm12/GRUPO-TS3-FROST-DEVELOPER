#!/usr/bin/env python3
"""Gera manifest.json (versão + SHA-256 dos arquivos que o app baixa ao atualizar)."""
import hashlib, json, os, sys
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
files = ["server.py", "updater.py", "index.html", "skin-frost.jpg", "icon.png", "version.txt"]
version = open(os.path.join(root, "version.txt")).read().strip()
notes = sys.argv[1] if len(sys.argv) > 1 else ""
m = {"version": version, "notes": notes,
     "files": {f: hashlib.sha256(open(os.path.join(root, f), "rb").read()).hexdigest() for f in files}}
with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(m, fh, ensure_ascii=False, indent=2)
print("manifest.json -> versão", version)
