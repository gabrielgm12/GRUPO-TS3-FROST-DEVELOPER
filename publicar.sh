#!/bin/bash
# Publica uma atualização no GitHub:  ./publicar.sh 1.3 "o que mudou"
# Quem já tem o app instalado baixa sozinho (o app lê o manifest.json do repositório).
set -e
cd "$(dirname "$0")"
[ -z "$1" ] && { echo "uso: ./publicar.sh <versao> \"notas\""; exit 1; }
echo "$1" > version.txt
sed -i '' "s/^!define VERSAO .*/!define VERSAO \"$1\"/" windows/instalador.nsi 2>/dev/null || true
python3 -m py_compile server.py updater.py
python3 tools/make_manifest.py "$2"
git add -A
git commit -m "v$1: ${2:-atualização}" || true
git push origin main
echo "Publicado v$1."
