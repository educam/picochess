#!/usr/bin/env bash
# Roda o PicoChess localmente, sem tabuleiro (board-type = noeboard), na porta 8080.
# Uso: ./meu/run-local.sh   (a partir da raiz do repo)  -> abra http://localhost:8080
set -euo pipefail
cd "$(dirname "$0")/.."

ARCH=$(uname -m)   # x86_64 ou aarch64 (Mac/Windows: ver docs/mac-install.md e docs/windows-install.md)

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

if [ ! -x "engines/$ARCH/a-stockf" ]; then
  mkdir -p "engines/$ARCH"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/eng.tgz" \
    "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/engines-$ARCH-small.tar.gz"
  tar -xzf "$tmp/eng.tgz" -C "engines/$ARCH"
fi

if [ ! -f picochess.ini ]; then
  sed -e "s#/opt/picochess/#$PWD/#g" \
      -e 's/^web-server = 80$/web-server = 8080/' \
      -e 's/^log-level = warning/log-level = info/' \
      "picochess.ini.example-web-$ARCH" > picochess.ini
fi

SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy} exec .venv/bin/python picochess.py
