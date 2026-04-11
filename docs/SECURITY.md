# M.A.R.I.A. - Security Guide

## Architektura bezpieczenstwa

```
Internet
   |
[Fritz!Box] ---- WireGuard VPN (zdalny dostep)
   |                    |
   |-- Siec glowna (192.168.1.x)
   |     |-- Mini PC (Maria)  <-- SSH + Web UI
   |     |-- Twoj laptop
   |     |-- Telefon
   |
   |-- Siec gosc (izolowana)
         |-- Goscie WiFi (brak dostepu do Mini PC)
```

**Zasada:** Mini PC nie jest widoczny z Internetu. Dostep zdalny TYLKO przez VPN.

---

## 1. Fritz!Box - Konfiguracja

### 1.1 Siec gosc (izolacja gosciego WiFi)

Goscie laczacy sie z WiFi NIE powinni widziec mini PC.

1. Zaloguj sie do Fritz!Box: `http://fritz.box`
2. **WiFi > Siec gosc** (Gastnetz)
3. Wlacz: "Gastzugang aktiv" / "Guest access active"
4. Zaznacz: "Gerate durfen untereinander kommunizieren" = **NIE** (odznacz)
5. Ustaw osobne haslo dla sieci gosc
6. Zapisz

Od teraz goscie maja Internet, ale nie widza Twoich urzadzen.

### 1.2 WireGuard VPN (zdalny dostep)

Fritz!Box od firmware 7.39+ ma wbudowany WireGuard.

1. Zaloguj sie do Fritz!Box: `http://fritz.box`
2. **Internet > Freigaben > VPN (WireGuard)**
3. "VPN-Verbindung hinzufugen" (dodaj polaczenie VPN)
4. Wybierz: "Einzelgerat verbinden" (polacz pojedyncze urzadzenie)
5. Nadaj nazwe: np. "Telefon-operator" lub "Laptop-zdalny"
6. Fritz!Box wygeneruje konfiguracje - pobierz ja
7. Na telefonie/laptopie:
   - Zainstaluj WireGuard: https://www.wireguard.com/install/
   - Zaimportuj pobrany plik konfiguracji
8. Polacz sie z VPN -> masz dostep do calej sieci domowej

**Weryfikacja:** Po polaczeniu VPN, otworz `http://192.168.1.X:5000` (IP mini PC).

### 1.3 MyFRITZ! (Dynamic DNS)

Potrzebujesz stalego adresu do VPN (Twoj IP domowy sie zmienia).

1. Fritz!Box > **Internet > MyFRITZ!-Konto**
2. Zarejestruj konto MyFRITZ! (jesli jeszcze nie masz)
3. Twoj adres VPN: `twoja-nazwa.myfritz.net`
4. WireGuard uzywa tego adresu automatycznie w konfiguracji

### 1.4 Co NIE robic na Fritz!Box

- **NIE** otwieraj port forwarding do mini PC (port 22, 5000)
- **NIE** wlaczaj DMZ
- **NIE** udostepniaj Ollama (port 11434) na zewnatrz
- Caly zdalny dostep idzie TYLKO przez VPN

---

## 2. Mini PC - Hardening

### 2.1 Automatyczny skrypt

```bash
sudo bash /home/maria/maria/scripts/setup_security.sh
```

Skrypt konfiguruje:

| Warstwa | Co robi | Szczegoly |
|---------|---------|-----------|
| **User** | `maria` bez sudo | Nie moze instalowac pakietow ani zmieniac systemu |
| **Firewall** | ufw - deny all incoming | Tylko SSH (22) i Web UI (5000) z LAN |
| **Fail2ban** | Blokada brute-force | 5 blednych prob SSH = ban na 1h |
| **Auto-updates** | unattended-upgrades | Security patches codziennie, auto |
| **SSH** | Hardened config | Root login off, timeout 5min, max 3 proby |
| **Pliki** | .env chmod 600 | Tylko maria moze czytac konfiguracje |

### 2.2 Klucz SSH (zamiast hasla)

Po uruchomieniu `setup_security.sh`, skonfiguruj logowanie kluczem:

**Na SWOIM laptopie** (nie na mini PC!):
```bash
# Wygeneruj klucz
ssh-keygen -t ed25519 -C "maria-minipc"

# Skopiuj na mini PC
ssh-copy-id maria@192.168.1.X

# Sprawdz czy dziala
ssh maria@192.168.1.X
# Powinno wpuscic BEZ hasla
```

**Po potwierdzeniu ze klucz dziala**, wylacz logowanie haslem:
```bash
# Na mini PC (jako root)
echo "PasswordAuthentication no" | sudo tee -a /etc/ssh/sshd_config.d/maria_hardening.conf
sudo systemctl reload sshd
```

### 2.3 Web UI

| Zabezpieczenie | Wartosc | Gdzie zmienic |
|----------------|---------|---------------|
| PIN | min 6 znakow | `.env` -> `MARIA_PIN` |
| Rate limit | 2 msg / 60 sec | `maria_ui/config.py` |
| Max message | 2000 znakow | `maria_ui/config.py` |
| Debug mode | false | `.env` -> `MARIA_DEBUG=false` |

---

## 3. Backup

### 3.1 Reczny backup
```bash
# Na dysk lokalny
bash /home/maria/maria/scripts/backup.sh

# Na USB
bash /home/maria/maria/scripts/backup.sh /media/usb
```

### 3.2 Automatyczny (cron)
```bash
crontab -e
# Dodaj:
0 3 * * * /home/maria/maria/scripts/backup.sh >> /home/maria/maria/logs/backup.log 2>&1
```

Backup trzyma max 7 kopii (starsze automatycznie kasowane).

### 3.3 Co jest backupowane

| Dane | Plik/folder | Krytycznosc |
|------|-------------|-------------|
| Pamiec dlugoterminowa | `memory/` | Wysoka |
| Wyniki egzaminow | `memory/exam_results.jsonl` | Wysoka |
| Graf semantyczny | `semantic_graph.json` | Wysoka |
| Nauczone koncepcje | `maria_learned_concepts.json` | Srednia |
| Model kodu | `meta_data/code_self_model.json` | Niska (regenerowany) |
| Logi homeostazy | `meta_data/homeostasis_events.jsonl` | Niska |
| Pliki wejsciowe | `input/` | Srednia |
| Konfiguracja | `.env` | Wysoka |

---

## 4. Checklist bezpieczenstwa

Przed oddaniem mini PC do pracy, sprawdz:

- [ ] `setup_security.sh` uruchomiony
- [ ] PIN zmieniony (nie "1234" i nie "zmien-mnie-123")
- [ ] `MARIA_DEBUG=false` w `.env`
- [ ] SSH klucz skonfigurowany
- [ ] Fritz!Box: siec gosc wlaczona
- [ ] Fritz!Box: VPN (WireGuard) skonfigurowany
- [ ] Fritz!Box: BRAK port forwarding do mini PC
- [ ] Backup dziala (`bash scripts/backup.sh`)
- [ ] Cron backup ustawiony
- [ ] `sudo ufw status` - firewall aktywny
- [ ] `sudo fail2ban-client status sshd` - fail2ban aktywny

---

## 5. Co robic w razie problemu

### Ktos probuje wlamac sie na SSH
```bash
# Sprawdz logi fail2ban
sudo fail2ban-client status sshd

# Zbanowane IP
sudo fail2ban-client banned

# Logi SSH
journalctl -u sshd --since "1 hour ago"
```

### Podejrzana aktywnosc w sieci
```bash
# Kto jest polaczony
ss -tuln

# Aktywne polaczenia
ss -tupn
```

### Zapomnialem PIN do Web UI
```bash
# Na mini PC przez SSH:
nano /home/maria/maria/.env
# Zmien MARIA_PIN=nowy-pin
sudo systemctl restart maria-ui
```

### Chce zmienic subnet LAN
```bash
# Jesli Fritz!Box uzywa innego subnetu niz 192.168.1.x:
sudo ufw status numbered
# Usun stare reguly i dodaj nowe:
sudo ufw delete <numer>
sudo ufw allow from 192.168.NOWY.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.NOWY.0/24 to any port 5000 proto tcp
```
