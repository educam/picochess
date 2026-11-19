#!/usr/bin/env bash
# Roda o PicoChess localmente no Linux, sem tabuleiro (board-type = noeboard), na porta 8080.
# Uso: ./meu/run-local.sh   (de qualquer pasta)  -> abra http://localhost:8080
# macOS e Windows: use install-picochess-mac.sh / install-picochess-windows.ps1 e os scripts start-* (ver docs/).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)" != "Linux" ]; then
  echo "Este script é para Linux. No macOS use: bash ./install-picochess-mac.sh && bash ./start-picochess-mac.sh" >&2
  exit 1
fi
ARCH=$(uname -m)   # x86_64 ou aarch64

[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

if [ ! -x "engines/$ARCH/a-stockf" ]; then
  mkdir -p "engines/$ARCH"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/eng.tgz" \
    "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/engines-$ARCH-small.tar.gz"
  tar -xzf "$tmp/eng.tgz" -C "engines/$ARCH"
  rm -rf "$tmp"
fi

if [ ! -f picochess.ini ]; then
  # Os caminhos /opt/picochess do exemplo são mapeados para esta pasta automaticamente.
  sed -e 's/^web-server = 80$/web-server = 8080/' "picochess.ini.example-web-$ARCH" > picochess.ini
fi

SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy} exec venv/bin/python picochess.py
