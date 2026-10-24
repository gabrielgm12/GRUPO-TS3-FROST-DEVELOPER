#!/bin/bash
# Gera windows/Instalar-Grupos-TS3.exe (precisa: brew install makensis, e windows/build/python = Python embutido p/ Windows)
set -e
cd "$(dirname "$0")"
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
makensis -V2 instalador.nsi
ls -lh Instalar-Grupos-TS3.exe
