# M.A.R.I.A. - Security Guide

M.A.R.I.A. runs locally on hardware you control. This document has two parts:
the project's **vulnerability-disclosure policy** (immediately below), and an
**operational hardening runbook** for self-hosting Maria on a home network
([appendix](#appendix-self-hosting-hardening-runbook)).

## Reporting a Vulnerability

**Please do not open a public issue for security problems.**

Instead, use one of these private channels:

- GitHub's **[Report a vulnerability](https://github.com/erykaitools-beep/Maria/security/advisories/new)** flow (preferred), or
- contact the maintainer through their GitHub profile.

Please include:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- the affected component and, if known, the commit.

We aim to acknowledge a report within **72 hours** and to share a fix or
mitigation timeline after triage.

## Scope

M.A.R.I.A. is offline-first and runs locally on hardware you control. The most
security-relevant areas are:

- the Flask Web UI (PIN-protected) and its network binding (`MARIA_HOST` / `MARIA_PORT`);
- secret handling — `.env` holds the PIN and any optional tokens and is never committed;
- optional integrations that take credentials (Telegram bot token, NVIDIA NIM key).

Out of scope: attacks that assume an already-compromised host, and the intended
behavior of a self-hosted agent acting on your own machine.

## Supported versions

This is a single-branch project; security fixes land on `main`.

---

# Appendix: Self-Hosting Hardening Runbook

> The sections below are operational guidance for running Maria on a home LAN
> behind a router and VPN. They are hardening recommendations for your own
> deployment, not part of the disclosure policy above. Example addresses such
> as `192.168.1.x` are placeholders — substitute your own subnet.

## Security architecture

```
Internet
   |
[Fritz!Box] ---- WireGuard VPN (remote access)
   |                    |
   |-- Main network (192.168.1.x)
   |     |-- Mini PC (Maria)  <-- SSH + Web UI
   |     |-- Your laptop
   |     |-- Phone
   |
   |-- Guest network (isolated)
         |-- Guest WiFi (no access to the Mini PC)
```

**Principle:** the Mini PC is not reachable from the Internet. Remote access is available ONLY over the VPN.

---

## 1. Fritz!Box configuration

### 1.1 Guest network (isolating guest WiFi)

Guests connecting to WiFi should NOT be able to see the Mini PC.

1. Log in to the Fritz!Box: `http://fritz.box`
2. **WiFi > Guest network** (Gastnetz)
3. Enable: "Gastzugang aktiv" / "Guest access active"
4. Set: "Gerate durfen untereinander kommunizieren" = **NO** (uncheck it)
5. Set a separate password for the guest network
6. Save

From now on, guests have Internet access but cannot see your devices.

### 1.2 WireGuard VPN (remote access)

Fritz!Box firmware 7.39+ ships with built-in WireGuard.

1. Log in to the Fritz!Box: `http://fritz.box`
2. **Internet > Freigaben > VPN (WireGuard)**
3. "VPN-Verbindung hinzufugen" (add a VPN connection)
4. Choose: "Einzelgerat verbinden" (connect a single device)
5. Give it a name, e.g. "phone-operator" or "laptop-remote"
6. The Fritz!Box generates a configuration — download it
7. On the phone/laptop:
   - Install WireGuard: https://www.wireguard.com/install/
   - Import the downloaded configuration file
8. Connect to the VPN -> you now have access to the entire home network

**Verification:** once connected to the VPN, open `http://192.168.1.X:5000` (the Mini PC's IP).

### 1.3 MyFRITZ! (Dynamic DNS)

You need a stable address for the VPN (your home IP changes over time).

1. Fritz!Box > **Internet > MyFRITZ!-Konto**
2. Register a MyFRITZ! account (if you don't have one yet)
3. Your VPN address: `your-name.myfritz.net`
4. WireGuard uses this address automatically in the configuration

### 1.4 What NOT to do on the Fritz!Box

- Do **NOT** open port forwarding to the Mini PC (ports 22, 5000)
- Do **NOT** enable DMZ
- Do **NOT** expose Ollama (port 11434) to the outside
- All remote access goes ONLY through the VPN

---

## 2. Mini PC hardening

### 2.1 Automated script

```bash
sudo bash /home/maria/maria/scripts/setup_security.sh
```

The script configures:

| Layer | What it does | Details |
|---------|---------|-----------|
| **User** | `maria` without sudo | Cannot install packages or change the system |
| **Firewall** | ufw — deny all incoming | Only SSH (22) and Web UI (5000) from the LAN |
| **Fail2ban** | Brute-force protection | 5 failed SSH attempts = 1h ban |
| **Auto-updates** | unattended-upgrades | Daily security patches, automatic |
| **SSH** | Hardened config | Root login off, 5 min timeout, max 3 attempts |
| **Files** | .env chmod 600 | Only maria can read the configuration |

### 2.2 SSH key (instead of a password)

After running `setup_security.sh`, set up key-based login:

**On YOUR laptop** (not on the Mini PC!):
```bash
# Generate the key
ssh-keygen -t ed25519 -C "maria-minipc"

# Copy it to the Mini PC
ssh-copy-id maria@192.168.1.X

# Check that it works
ssh maria@192.168.1.X
# Should log in WITHOUT a password
```

**Once you've confirmed the key works**, disable password login:
```bash
# On the Mini PC (as root)
echo "PasswordAuthentication no" | sudo tee -a /etc/ssh/sshd_config.d/maria_hardening.conf
sudo systemctl reload sshd
```

### 2.3 Web UI

| Protection | Value | Where to change |
|----------------|---------|---------------|
| PIN | min 6 characters | `.env` -> `MARIA_PIN` |
| Rate limit | 2 msg / 60 sec | `maria_ui/config.py` |
| Max message | 2000 characters | `maria_ui/config.py` |
| Debug mode | false | `.env` -> `MARIA_DEBUG=false` |

---

## 3. Backup

### 3.1 Manual backup
```bash
# To local disk
bash /home/maria/maria/scripts/backup.sh

# To USB
bash /home/maria/maria/scripts/backup.sh /media/usb
```

### 3.2 Automated (cron)
```bash
crontab -e
# Add:
0 3 * * * /home/maria/maria/scripts/backup.sh >> /home/maria/maria/logs/backup.log 2>&1
```

The backup keeps a maximum of 7 copies (older ones are deleted automatically).

### 3.3 What gets backed up

| Data | File/folder | Criticality |
|------|-------------|-------------|
| Long-term memory | `memory/` | High |
| Exam results | `memory/exam_results.jsonl` | High |
| Semantic graph | `semantic_graph.json` | High |
| Learned concepts | `maria_learned_concepts.json` | Medium |
| Code model | `meta_data/code_self_model.json` | Low (regenerated) |
| Homeostasis logs | `meta_data/homeostasis_events.jsonl` | Low |
| Input files | `input/` | Medium |
| Configuration | `.env` | High |

---

## 4. Security checklist

Before putting the Mini PC into service, verify:

- [ ] `setup_security.sh` has been run
- [ ] PIN changed (not "1234" and not "change-me-123")
- [ ] `MARIA_DEBUG=false` in `.env`
- [ ] SSH key configured
- [ ] Fritz!Box: guest network enabled
- [ ] Fritz!Box: VPN (WireGuard) configured
- [ ] Fritz!Box: NO port forwarding to the Mini PC
- [ ] Backup works (`bash scripts/backup.sh`)
- [ ] Cron backup set up
- [ ] `sudo ufw status` — firewall active
- [ ] `sudo fail2ban-client status sshd` — fail2ban active

---

## 5. Incident response

### Someone is trying to break in over SSH
```bash
# Check fail2ban logs
sudo fail2ban-client status sshd

# Banned IPs
sudo fail2ban-client banned

# SSH logs
journalctl -u sshd --since "1 hour ago"
```

### Suspicious network activity
```bash
# Listening ports
ss -tuln

# Active connections
ss -tupn
```

### I forgot the Web UI PIN
```bash
# On the Mini PC over SSH:
nano /home/maria/maria/.env
# Change MARIA_PIN=new-pin
sudo systemctl restart maria-ui
```

### I want to change the LAN subnet
```bash
# If the Fritz!Box uses a subnet other than 192.168.1.x:
sudo ufw status numbered
# Remove the old rules and add new ones:
sudo ufw delete <number>
sudo ufw allow from 192.168.NEW.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.NEW.0/24 to any port 5000 proto tcp
```
