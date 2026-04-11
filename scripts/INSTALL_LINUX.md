# M.A.R.I.A. - Linux Installation Guide (Mini PC)

## Hardware
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu 22.04+ or Debian 12+

## Kolejnosc instalacji

1. System Setup (Python, git)
2. Ollama
3. Deploy Maria
4. **Security hardening** (setup_security.sh)
5. Configuration (.env)
6. Copy Memory Data
7. Test Run
8. Install as Services
9. Backup (cron)

---

## 1. System Setup

```bash
# Install Python and tools
sudo apt update
sudo apt install python3 python3-pip python3-venv git curl
```

## 2. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull llama3.1:8b

# Verify
curl http://localhost:11434/api/tags
```

## 3. Deploy Maria

```bash
# Switch to maria user (utworzony w kroku 4, lub utwórz recznie)
sudo useradd -m -s /bin/bash maria
sudo su - maria

# Copy project from USB
cp -r /media/usb/maria /home/maria/maria
# Or: git clone <REPO_URL> /home/maria/maria

# Create virtual environment
cd /home/maria/maria
python3 -m venv venv
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

## 4. Security Hardening

```bash
# Uruchom skrypt hardening (jako root/sudo, NIE jako maria)
sudo bash /home/maria/maria/scripts/setup_security.sh
```

Skrypt automatycznie:
- Upewnia sie ze user `maria` nie ma sudo
- Konfiguruje firewall (SSH + Web UI tylko z LAN)
- Instaluje fail2ban (blokuje brute-force)
- Wlacza automatyczne security updates
- Hardenuje SSH (root login off, timeout, max 3 proby)
- Ustawia uprawnienia plikow

Wiecej szczegolow: `docs/SECURITY.md`

## 5. Configuration

```bash
# Przejdz na usera maria
sudo su - maria
cd /home/maria/maria

# Utworz .env z szablonu
cp .env.example .env

# Edytuj konfiguracje
nano .env
# KONIECZNIE zmien:
#   MARIA_PIN=<twoj-silny-pin>   (min 6 znakow!)
#   MARIA_DEBUG=false
```

## 6. Copy Memory Data (from old machine)

```bash
# Copy these directories from backup/USB:
cp -r /media/usb/backup/memory/ /home/maria/maria/memory/
cp -r /media/usb/backup/meta_data/ /home/maria/maria/meta_data/
cp /media/usb/backup/semantic_graph.json /home/maria/maria/

# Copy input files if needed
cp -r /media/usb/backup/input/ /home/maria/maria/input/
```

## 7. Test Run

```bash
cd /home/maria/maria
source venv/bin/activate

# Run tests
python -m pytest agent_core/tests/ -v

# Test REPL (manual)
python main.py
# Try: /homeostasis, /introspect, /help
# Exit: /exit

# Test Web UI
python run_ui.py
# Open http://<MINI_PC_IP>:5000 from another device
```

## 8. Install as Services (auto-start)

```bash
# Copy service files
sudo cp /home/maria/maria/scripts/maria.service /etc/systemd/system/
sudo cp /home/maria/maria/scripts/maria-ui.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable maria maria-ui
sudo systemctl start maria maria-ui

# Check status
sudo systemctl status maria
sudo systemctl status maria-ui
```

## 9. Setup Backup (cron)

```bash
# Testowy backup
bash /home/maria/maria/scripts/backup.sh

# Automatyczny backup codziennie o 3:00
crontab -e
# Dodaj linie:
# 0 3 * * * /home/maria/maria/scripts/backup.sh >> /home/maria/maria/logs/backup.log 2>&1

# Backup na USB (recznie):
bash /home/maria/maria/scripts/backup.sh /media/usb
```

---

## Monitoring

```bash
# View Maria logs
journalctl -u maria -f

# View Web UI logs
journalctl -u maria-ui -f

# Check service status
sudo systemctl status maria maria-ui

# Check firewall
sudo ufw status

# Check fail2ban
sudo fail2ban-client status sshd
```

## Troubleshooting

### Ollama not responding
```bash
systemctl status ollama
sudo systemctl restart ollama
journalctl -u ollama -n 50
```

### Permission errors
```bash
sudo chown -R maria:maria /home/maria/maria
chmod 600 /home/maria/maria/.env
```

### Python module not found
```bash
cd /home/maria/maria
source venv/bin/activate
python main.py
```

### Firewall blocks connection
```bash
# Sprawdz reguly
sudo ufw status verbose

# Jesli Twoja siec to nie 192.168.1.x, zmien reguly:
sudo ufw delete allow from 192.168.1.0/24 to any port 5000
sudo ufw allow from 192.168.YOUR.0/24 to any port 5000 proto tcp
```

### SSH klucz nie dziala
```bash
# Na mini PC sprawdz uprawnienia
chmod 700 /home/maria/.ssh
chmod 600 /home/maria/.ssh/authorized_keys
chown -R maria:maria /home/maria/.ssh
```
