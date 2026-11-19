#!/usr/bin/env bash
# Reforço de segurança para um Raspberry Pi dedicado ao PicoChess.
#
# Uso (no Pi, dentro de /opt/picochess):
#   sudo ./meu/harden-pi.sh            # só verifica e mostra o plano (não muda nada)
#   sudo ./meu/harden-pi.sh --apply    # aplica
#   sudo ./meu/harden-pi.sh --undo     # desfaz o que --apply fez
#
# Opções extras com --apply:
#   --ssh-keys-only   desliga login SSH por senha (só se você já tiver chave em ~/.ssh/authorized_keys)
#   --no-mdns         desliga o avahi (picochess.local deixa de funcionar; use o IP)
#
# O que fica ligado de propósito, porque o PicoChess precisa:
#   - ssh, bluetooth/hciuart (tabuleiro DGT Bluetooth), NetworkManager, avahi (picochess.local)
#   - picochess, gamesdb (porta 7778, aba GAMES), picochess-update, unblock-bt
#   - sudo sem senha do usuário: o PicoChess usa "sudo" para parear o DGT Bluetooth (rfcomm),
#     reiniciar, desligar e se atualizar. Tirar isso quebra essas funções.
set -euo pipefail

STATE_DIR=/var/lib/picochess-hardening
STATE_SERVICES=$STATE_DIR/disabled-services
SSH_DROPIN=/etc/ssh/sshd_config.d/90-picochess-hardening.conf
SYSCTL_FILE=/etc/sysctl.d/90-picochess-hardening.conf
F2B_JAIL=/etc/fail2ban/jail.d/picochess-sshd.conf
AUTO_UPGRADES=/etc/apt/apt.conf.d/20auto-upgrades
PICO_DIR=$(cd "$(dirname "$0")/.." && pwd)
PICO_INI=$PICO_DIR/picochess.ini
PRIVATE_NETS="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"

# Serviços que um Pi só de PicoChess não usa (só mexe nos que existirem e estiverem ligados).
CANDIDATES="cups cups-browsed rpcbind nfs-server smbd nmbd samba-ad-dc triggerhappy ModemManager
vncserver-x11-serviced wayvnc exim4 postfix apache2 lighttpd nginx telnet.socket xrdp avahi-daemon"

MODE=check
SSH_KEYS_ONLY=false
NO_MDNS=false
for arg in "$@"; do
    case "$arg" in
        --apply) MODE=apply ;;
        --undo) MODE=undo ;;
        --check) MODE=check ;;
        --ssh-keys-only) SSH_KEYS_ONLY=true ;;
        --no-mdns) NO_MDNS=true ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Rode com sudo: sudo $0 $*" >&2
    exit 1
fi

USER_NAME=${SUDO_USER:-pi}
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
# IP de quem está conectado por SSH agora (sudo apaga SSH_CONNECTION, então "who am i" é o plano B).
SSH_CLIENT_IP=""
if [ -n "${SSH_CONNECTION:-}" ]; then
    SSH_CLIENT_IP=${SSH_CONNECTION%% *}
else
    SSH_CLIENT_IP=$(who am i 2>/dev/null | sed -n 's/.*(\([0-9a-fA-F.:]*\)).*/\1/p' | head -1)
fi

section() { printf '\n== %s ==\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
unit_exists() { systemctl list-unit-files "$1" "$1.service" 2>/dev/null | grep -qE "^$1(\.service)?[[:space:]]"; }
unit_enabled() { systemctl is-enabled "$1" >/dev/null 2>&1; }

web_port() {
    local port=""
    if [ -f "$PICO_INI" ]; then
        port=$(sed -n 's/^[[:space:]]*web-server[[:space:]]*=[[:space:]]*\([0-9]\+\).*/\1/p' "$PICO_INI" | head -1)
    fi
    echo "${port:-80}"
}

services_to_disable() {
    local svc
    for svc in $CANDIDATES; do
        if [ "$svc" = "avahi-daemon" ] && [ "$NO_MDNS" != true ]; then
            continue
        fi
        if unit_exists "$svc" && unit_enabled "$svc"; then
            echo "$svc"
        fi
    done
}

has_ssh_key() {
    [ -s "$USER_HOME/.ssh/authorized_keys" ]
}

report() {
    section "Sistema"
    echo "Usuário: $USER_NAME   Conexão SSH vinda de: ${SSH_CLIENT_IP:-(não é SSH)}"
    [ -r /etc/os-release ] && . /etc/os-release && echo "Sistema: ${PRETTY_NAME:-?}"

    section "Portas abertas para a rede"
    if have ss; then
        ss -tulpnH 2>/dev/null | awk '$5 !~ /^(127\.|\[::1\]|::1)/ {print "  " $1 "  " $5 "  " $7}' | sort -u
    fi

    section "Serviços que seriam desligados"
    local list
    list=$(services_to_disable)
    if [ -n "$list" ]; then echo "$list" | sed 's/^/  /'; else echo "  (nenhum)"; fi

    section "SSH"
    if have sshd; then
        sshd -T 2>/dev/null | grep -E '^(permitrootlogin|passwordauthentication|x11forwarding|maxauthtries) ' | sed 's/^/  /'
    fi
    if has_ssh_key; then echo "  Chave SSH encontrada para $USER_NAME: pode usar --ssh-keys-only"; else
        echo "  Sem chave SSH para $USER_NAME: o login por senha continua ligado"; fi

    section "Firewall"
    if have ufw; then ufw status | sed 's/^/  /'; else echo "  ufw não instalado (será instalado)"; fi

    section "Plano para --apply"
    echo "  - desligar os serviços listados acima"
    echo "  - SSH: sem login de root, sem X11, no máximo 3 tentativas$( $SSH_KEYS_ONLY && echo ', só com chave')"
    local web
    web=$(web_port)
    [ "$web" = 8080 ] && web="8080" || web="$web e 8080"
    echo "  - firewall (ufw): bloquear entrada; liberar só das redes privadas: 22 (SSH), $web (PicoChess), 7778 (aba GAMES)"
    echo "  - fail2ban: bloquear quem errar a senha SSH várias vezes"
    echo "  - atualizações automáticas de segurança (unattended-upgrades)"
    echo "  - ajustes de rede do kernel (sem redirects, sem source routing, rp_filter)"
    echo "  - PicoChess: allow-onboard-without-auth = false (página de Wi-Fi passa a pedir login)"
    echo "  Fica como está: sudo sem senha, Bluetooth, avahi$( $NO_MDNS && echo ' (exceto: será desligado)'), serviços do PicoChess"
}

apply() {
    mkdir -p "$STATE_DIR"
    : > "$STATE_SERVICES.new"

    section "Desligando serviços"
    local svc
    for svc in $(services_to_disable); do
        systemctl disable --now "$svc" >/dev/null 2>&1 && echo "  desligado: $svc" && echo "$svc" >> "$STATE_SERVICES.new"
    done
    [ -f "$STATE_SERVICES" ] && cat "$STATE_SERVICES" >> "$STATE_SERVICES.new"
    sort -u "$STATE_SERVICES.new" > "$STATE_SERVICES"
    rm -f "$STATE_SERVICES.new"

    section "SSH"
    if $SSH_KEYS_ONLY && ! has_ssh_key; then
        echo "  --ssh-keys-only ignorado: não há chave em $USER_HOME/.ssh/authorized_keys (você ficaria trancado fora)"
        SSH_KEYS_ONLY=false
    fi
    {
        echo "# Criado por meu/harden-pi.sh"
        echo "PermitRootLogin no"
        echo "X11Forwarding no"
        echo "MaxAuthTries 3"
        echo "LoginGraceTime 30"
        echo "PermitEmptyPasswords no"
        $SSH_KEYS_ONLY && echo "PasswordAuthentication no"
    } > "$SSH_DROPIN"
    if sshd -t; then
        systemctl reload ssh 2>/dev/null || systemctl reload sshd
        echo "  configuração aplicada (sua sessão atual continua aberta)"
    else
        rm -f "$SSH_DROPIN"
        echo "  configuração inválida, nada mudou no SSH" >&2
    fi

    section "Pacotes de segurança"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ufw fail2ban unattended-upgrades >/dev/null
    echo "  ufw, fail2ban e unattended-upgrades instalados"

    section "Firewall"
    local port net ports
    ports="22 $(web_port) 8080 7778"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    for net in $PRIVATE_NETS; do
        for port in $(echo "$ports" | tr ' ' '\n' | sort -un); do
            ufw allow from "$net" to any port "$port" proto tcp comment picochess >/dev/null
        done
    done
    if [ -n "$SSH_CLIENT_IP" ]; then
        ufw allow from "$SSH_CLIENT_IP" to any port 22 proto tcp comment "sessao atual" >/dev/null
    fi
    ufw --force enable >/dev/null
    ufw status | sed 's/^/  /'

    section "fail2ban"
    cat > "$F2B_JAIL" <<'EOF'
# Criado por meu/harden-pi.sh
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ::1
EOF
    systemctl enable --now fail2ban >/dev/null 2>&1 || true
    systemctl restart fail2ban || true
    echo "  ativo para o SSH (5 erros em 10 min = bloqueio de 1 h)"

    section "Atualizações automáticas"
    if [ ! -f "$AUTO_UPGRADES" ]; then
        printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > "$AUTO_UPGRADES"
        touch "$STATE_DIR/created-auto-upgrades"
    fi
    echo "  atualizações de segurança diárias ligadas"

    section "Kernel"
    cat > "$SYSCTL_FILE" <<'EOF'
# Criado por meu/harden-pi.sh
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
EOF
    sysctl -q --system >/dev/null 2>&1 || true
    echo "  aplicado"

    section "PicoChess"
    if [ -f "$PICO_INI" ]; then
        if grep -qE '^[#[:space:]]*allow-onboard-without-auth' "$PICO_INI"; then
            sed -i -E 's/^[#[:space:]]*allow-onboard-without-auth.*/allow-onboard-without-auth = false/' "$PICO_INI"
        else
            echo "allow-onboard-without-auth = false" >> "$PICO_INI"
        fi
        echo "  página de Wi-Fi agora pede login (vale após reiniciar o PicoChess)"
    else
        echo "  $PICO_INI não encontrado, nada mudou"
    fi

    section "Pronto"
    echo "  Teste agora, SEM fechar esta sessão, numa segunda janela:"
    echo "    ssh $USER_NAME@<ip-do-pi>"
    echo "  e abra http://<ip-do-pi> no browser. Se algo falhar: sudo $0 --undo"
}

undo() {
    section "Religando serviços"
    if [ -f "$STATE_SERVICES" ]; then
        while read -r svc; do
            [ -n "$svc" ] && systemctl enable --now "$svc" >/dev/null 2>&1 && echo "  religado: $svc"
        done < "$STATE_SERVICES"
        rm -f "$STATE_SERVICES"
    fi
    section "SSH"
    if [ -f "$SSH_DROPIN" ]; then
        rm -f "$SSH_DROPIN"
        sshd -t && (systemctl reload ssh 2>/dev/null || systemctl reload sshd) && echo "  configuração original"
    fi
    section "Firewall e fail2ban"
    have ufw && ufw --force disable >/dev/null && echo "  ufw desligado"
    if [ -f "$F2B_JAIL" ]; then rm -f "$F2B_JAIL"; systemctl restart fail2ban 2>/dev/null || true; echo "  regra do fail2ban removida"; fi
    section "Outros"
    rm -f "$SYSCTL_FILE" && sysctl -q --system >/dev/null 2>&1 || true
    if [ -f "$STATE_DIR/created-auto-upgrades" ]; then rm -f "$AUTO_UPGRADES" "$STATE_DIR/created-auto-upgrades"; fi
    if [ -f "$PICO_INI" ]; then
        sed -i -E 's/^allow-onboard-without-auth = false$/allow-onboard-without-auth = true/' "$PICO_INI"
    fi
    echo "  desfeito (os pacotes ufw/fail2ban/unattended-upgrades continuam instalados, sem efeito)"
}

case "$MODE" in
    check) report; echo; echo "Nada foi alterado. Para aplicar: sudo $0 --apply" ;;
    apply) report; apply ;;
    undo) undo ;;
esac
