# M.A.R.I.A. - Linux Installation Guide (Mini PC)

## Hardware
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu 22.04+ or Debian 12+

## 1. System Setup

```bash
# Create user
sudo useradd -m -s /bin/bash maria
sudo passwd maria

# Install Python
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
# Switch to maria user
sudo su - maria

# Clone or copy project
git clone <REPO_URL> /home/maria/maria
# Or copy from USB: cp -r /media/usb/maria /home/maria/maria

# Create virtual environment
cd /home/maria/maria
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r maria_core/requirements.txt
pip install -r maria_ui/requirements.txt
```

## 4. Configuration

```bash
cd /home/maria/maria

# Create .env from template
cp .env.example .env

# Edit configuration
nano .env
# Change at minimum:
#   MARIA_PIN=<your-secure-pin>
#   MARIA_DEBUG=false
```

## 5. Copy Memory Data (from old machine)

```bash
# Copy these directories from backup/USB:
cp -r /media/usb/backup/memory/ /home/maria/maria/memory/
cp -r /media/usb/backup/meta_data/ /home/maria/maria/meta_data/
cp /media/usb/backup/semantic_graph.json /home/maria/maria/

# Copy input files if needed
cp -r /media/usb/backup/input/ /home/maria/maria/input/
```

## 6. Test Run

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

## 7. Install as Services (auto-start)

```bash
# Copy service files
sudo cp /home/maria/maria/scripts/maria.service /etc/systemd/system/
sudo cp /home/maria/maria/scripts/maria-ui.service /etc/systemd/system/

# Edit paths if needed
sudo nano /etc/systemd/system/maria.service
sudo nano /etc/systemd/system/maria-ui.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable maria maria-ui
sudo systemctl start maria maria-ui

# Check status
sudo systemctl status maria
sudo systemctl status maria-ui
```

## 8. Firewall (if enabled)

```bash
# Allow Web UI access from LAN
sudo ufw allow 5000/tcp comment "Maria Web UI"

# Ollama is only needed locally, no firewall rule needed
```

## 9. Monitoring

```bash
# View Maria logs
journalctl -u maria -f

# View Web UI logs
journalctl -u maria-ui -f

# Check service status
sudo systemctl status maria maria-ui
```

## Troubleshooting

### Ollama not responding
```bash
# Check if running
systemctl status ollama

# Restart
sudo systemctl restart ollama

# Check logs
journalctl -u ollama -n 50
```

### Permission errors
```bash
# Ensure maria user owns the project directory
sudo chown -R maria:maria /home/maria/maria
```

### Python module not found
```bash
# Always run from project root
cd /home/maria/maria
source venv/bin/activate
python main.py
```
