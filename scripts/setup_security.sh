#!/bin/bash
# =============================================================================
# M.A.R.I.A. - Security Hardening Script
# =============================================================================
# Uruchom jako root (sudo) na swiezym Ubuntu 22.04+ / Debian 12+
#
# Uzycie:
#   sudo bash /home/maria/maria/scripts/setup_security.sh
#
# Co robi:
#   1. Tworzy usera 'maria' (bez sudo)
#   2. Konfiguruje firewall (ufw) - tylko SSH + Web UI z LAN
#   3. Instaluje fail2ban (blokuje brute-force SSH)
#   4. Wlacza automatyczne aktualizacje bezpieczenstwa
#   5. Hardenuje SSH (klucz zamiast hasla)
#   6. Ustawia uprawnienia plikow
# =============================================================================

set -e

# Kolory
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[BLAD]${NC} $1"; }

# Sprawdz czy root
if [ "$EUID" -ne 0 ]; then
    error "Uruchom jako root: sudo bash $0"
    exit 1
fi

echo "============================================="
echo "  M.A.R.I.A. - Security Hardening"
echo "============================================="
echo ""

# -----------------------------------------------------------------
# 1. User 'maria' (bez sudo)
# -----------------------------------------------------------------
echo "--- 1/6 User 'maria' ---"

if id "maria" &>/dev/null; then
    info "User 'maria' juz istnieje"
else
    useradd -m -s /bin/bash maria
    info "Utworzono usera 'maria'"
    echo ""
    warn "Ustaw haslo dla usera 'maria':"
    passwd maria
fi

# Upewnij sie ze maria NIE jest w grupie sudo
if groups maria | grep -q "\bsudo\b"; then
    gpasswd -d maria sudo 2>/dev/null || true
    warn "Usunieto 'maria' z grupy sudo (bezpieczenstwo)"
fi

info "User 'maria' nie ma uprawnien sudo - OK"
echo ""

# -----------------------------------------------------------------
# 2. Firewall (ufw)
# -----------------------------------------------------------------
echo "--- 2/6 Firewall (ufw) ---"

apt-get install -y ufw > /dev/null 2>&1

# Domyslna polityka: blokuj wszystko przychodzace
ufw default deny incoming > /dev/null 2>&1
ufw default allow outgoing > /dev/null 2>&1

# SSH - tylko z sieci LAN
# Zmien ponizszy zakres na swoja siec lokalna
LAN_SUBNET="192.168.1.0/24"

ufw allow from $LAN_SUBNET to any port 22 proto tcp comment "SSH z LAN" > /dev/null 2>&1
info "SSH (port 22) - dozwolone tylko z $LAN_SUBNET"

# Web UI - tylko z LAN
ufw allow from $LAN_SUBNET to any port 5000 proto tcp comment "Maria Web UI z LAN" > /dev/null 2>&1
info "Web UI (port 5000) - dozwolone tylko z $LAN_SUBNET"

# Ollama - tylko localhost (domyslnie juz tak, ale dla pewnosci)
# Nie otwieramy portu 11434 - Ollama slucha tylko na 127.0.0.1

# Wlacz firewall
ufw --force enable > /dev/null 2>&1
info "Firewall wlaczony"
echo ""
ufw status numbered
echo ""

# -----------------------------------------------------------------
# 3. Fail2ban (ochrona SSH)
# -----------------------------------------------------------------
echo "--- 3/6 Fail2ban ---"

apt-get install -y fail2ban > /dev/null 2>&1

# Konfiguracja fail2ban dla SSH
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 1800
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s
maxretry = 5
bantime  = 3600
EOF

systemctl enable fail2ban > /dev/null 2>&1
systemctl restart fail2ban > /dev/null 2>&1
info "Fail2ban zainstalowany (5 prob -> ban na 1h)"
echo ""

# -----------------------------------------------------------------
# 4. Automatyczne aktualizacje bezpieczenstwa
# -----------------------------------------------------------------
echo "--- 4/6 Automatyczne aktualizacje ---"

apt-get install -y unattended-upgrades > /dev/null 2>&1

# Wlacz automatyczne aktualizacje bezpieczenstwa
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

systemctl enable unattended-upgrades > /dev/null 2>&1
info "Automatyczne security updates wlaczone (codziennie)"
echo ""

# -----------------------------------------------------------------
# 5. Hardening SSH
# -----------------------------------------------------------------
echo "--- 5/6 SSH hardening ---"

SSHD_CONFIG="/etc/ssh/sshd_config"
SSHD_HARDENING="/etc/ssh/sshd_config.d/maria_hardening.conf"

cat > "$SSHD_HARDENING" << 'EOF'
# M.A.R.I.A. SSH hardening
# Login root wylaczony
PermitRootLogin no

# Timeout nieaktywnej sesji (5 min)
ClientAliveInterval 300
ClientAliveCountMax 2

# Max prob logowania
MaxAuthTries 3

# Brak pustych hasel
PermitEmptyPasswords no

# Logowanie: wystarczajaco do debugowania
LogLevel INFO
EOF

# Sprawdz czy konfiguracja SSH jest poprawna
if sshd -t 2>/dev/null; then
    systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
    info "SSH: root login wylaczony, timeout 5min, max 3 proby"
else
    error "Blad w konfiguracji SSH - sprawdz recznie"
    rm -f "$SSHD_HARDENING"
fi

echo ""
warn "NASTEPNY KROK: Skonfiguruj klucz SSH (zamiast hasla)"
echo "  Na SWOIM laptopie (nie na mini PC!) uruchom:"
echo "    ssh-keygen -t ed25519 -C \"maria-minipc\""
echo "    ssh-copy-id maria@<MINI_PC_IP>"
echo ""
echo "  Po potwierdzeniu ze klucz dziala, dodaj do $SSHD_HARDENING:"
echo "    PasswordAuthentication no"
echo "  I zrestartuj SSH: sudo systemctl reload sshd"
echo ""

# -----------------------------------------------------------------
# 6. Uprawnienia plikow
# -----------------------------------------------------------------
echo "--- 6/6 Uprawnienia plikow ---"

MARIA_DIR="/home/maria/maria"

if [ -d "$MARIA_DIR" ]; then
    # Caly projekt nalezy do usera maria
    chown -R maria:maria "$MARIA_DIR"

    # .env - tylko maria moze czytac (hasla, PIN)
    if [ -f "$MARIA_DIR/.env" ]; then
        chmod 600 "$MARIA_DIR/.env"
        info ".env - uprawnienia 600 (tylko maria)"
    fi

    # Skrypty wykonywalne
    chmod +x "$MARIA_DIR/scripts/"*.sh 2>/dev/null || true

    info "Uprawnienia katalogu ustawione"
else
    warn "Katalog $MARIA_DIR nie istnieje jeszcze - ustaw uprawnienia po deploy"
fi

echo ""

# -----------------------------------------------------------------
# Podsumowanie
# -----------------------------------------------------------------
echo "============================================="
echo "  GOTOWE - Podsumowanie"
echo "============================================="
echo ""
info "User 'maria' (bez sudo)"
info "Firewall: SSH + WebUI tylko z LAN ($LAN_SUBNET)"
info "Fail2ban: 5 prob -> ban na 1h"
info "Auto-updates: security patches codziennie"
info "SSH: root off, timeout 5min, max 3 proby"
echo ""
warn "PAMIETAJ:"
echo "  1. Zmien PIN w .env (nie zostawiaj 1234!)"
echo "  2. Skonfiguruj klucz SSH (instrukcja powyzej)"
echo "  3. Wlacz WireGuard VPN w Fritz!Box (patrz SECURITY.md)"
echo "  4. Wlacz siec gosc w Fritz!Box dla gosciego WiFi"
echo ""
