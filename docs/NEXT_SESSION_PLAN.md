# Plan nastepnej sesji - Deploy Maria na Mini PC

## Stan poczatkowy
- [x] Mini PC: Ubuntu zainstalowany
- [x] Claude Code Desktop: SSH do mini PC dziala
- [ ] Ollama: jeszcze nie zainstalowana
- [ ] Maria: jeszcze nie skopiowana

## Dostep Claude Code
- **Laptop (Windows):** projekt w `C:\MariaLocal\Moja AI. Maria Ver.4`
- **Mini PC (Ubuntu):** przez SSH z Claude Code Desktop

## Kroki sesji

### Faza 1: Przygotowanie mini PC (przez SSH)

1. **Zainstaluj podstawowe narzedzia**
   ```bash
   sudo apt update && sudo apt install python3 python3-pip python3-venv git curl
   ```

2. **Zainstaluj Ollama**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull llama3.1:8b
   ```

3. **Utworz usera maria**
   ```bash
   sudo useradd -m -s /bin/bash maria
   sudo passwd maria
   ```

### Faza 2: Skopiuj projekt na mini PC

Opcja A - SCP z laptopa:
```bash
# Z laptopa (w bashu Claude Code):
scp -r "/c/MariaLocal/Moja AI. Maria Ver.4" eryk@<MINI_PC_IP>:/tmp/maria_transfer/

# Na mini PC:
sudo mv /tmp/maria_transfer /home/maria/maria
sudo chown -R maria:maria /home/maria/maria
```

Opcja B - USB:
```bash
# Eryk kopiuje recznie na USB -> mini PC
# Na mini PC:
sudo cp -r /media/usb/maria /home/maria/maria
sudo chown -R maria:maria /home/maria/maria
```

### Faza 3: Security hardening

```bash
# Na mini PC (jako root/sudo):
sudo bash /home/maria/maria/scripts/setup_security.sh
```

### Faza 4: Konfiguracja

```bash
# Na mini PC jako user maria:
sudo su - maria
cd /home/maria/maria
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Konfiguracja
cp .env.example .env
nano .env
# Zmienic: MARIA_PIN=<silny-pin>
```

### Faza 5: Test

```bash
# Testy
python -m pytest agent_core/tests/ -v

# REPL
python main.py
# /help, /homeostasis, /introspect, /exit

# Web UI
python run_ui.py
# Otworz http://<MINI_PC_IP>:5000 z laptopa
```

### Faza 6: Uslugi systemd (auto-start)

```bash
sudo cp /home/maria/maria/scripts/maria.service /etc/systemd/system/
sudo cp /home/maria/maria/scripts/maria-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable maria maria-ui
sudo systemctl start maria maria-ui
```

### Faza 7: Backup + cron

```bash
bash /home/maria/maria/scripts/backup.sh
crontab -e
# 0 3 * * * /home/maria/maria/scripts/backup.sh >> /home/maria/maria/logs/backup.log 2>&1
```

### Faza 8: Fritz!Box

Eryk robi recznie (nie przez SSH):
- [ ] Siec gosc wlaczona
- [ ] WireGuard VPN skonfigurowany
- [ ] Test VPN z telefonu

### Faza 9: NVIDIA NIM API (jesli starczy czasu)

- Utworzyc `agent_core/llm/nim_client.py`
- Dodac env vars: `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL`
- Routing: NIM do nauki, Ollama do chatu
- Test z prawdziwym kluczem

## Informacje potrzebne na poczatku sesji

Eryk powinien przygotowac:
1. **IP mini PC** w sieci LAN (np. 192.168.178.X)
2. **User/haslo SSH** do mini PC
3. **NVIDIA NIM API key** (jesli chcemy integrowac)
4. **Nowy PIN** do Web UI (nie "1234"!)

## Weryfikacja sukcesu

- [ ] `python -m pytest` - 340 testow passing na mini PC
- [ ] Web UI dostepne z laptopa przez LAN
- [ ] SSH z kluczem (bez hasla)
- [ ] Firewall aktywny (`sudo ufw status`)
- [ ] Fail2ban aktywny
- [ ] Backup dziala
- [ ] Systemd uslugi dzialaja po reboot
