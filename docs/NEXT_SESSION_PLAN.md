# Plan nastepnej sesji - Post NIM API

## Stan po sesji 2026-02-23
- [x] SSH key auth + PasswordAuthentication no
- [x] Reboot test - serwisy wstaja automatycznie
- [x] WireGuard VPN - dostep z telefonu (pamietaj: http:// nie https!)
- [x] NVIDIA NIM API - klient + router + budzet tokenow
- [x] 398 testow passing

## NIM API - gotowe do uzycia
| Komponent | Plik | Status |
|-----------|------|--------|
| NIM Client | `agent_core/llm/nim_client.py` | Zweryfikowany z API |
| Token Budget | `agent_core/llm/token_budget.py` | Persistence w JSON |
| LLM Router | `agent_core/llm/router.py` | Hybrid: NIM+Ollama |
| Model | `z-ai/glm5` | Dziala, ~2-5s latency |
| Budzet | 100k/dzien, 2M/miesiac | Konfigurowalny w .env |

## Nastepne kroki (priorytet)

### 1. Integracja NIM z istniejacym kodem
- [ ] Podlaczyc LLMRouter do `main.py` (zamienic `ctx.brain` na router)
- [ ] Podlaczyc do `brain_memory_integration.py` (nauka przez NIM)
- [ ] REPL command `/nim status` (budzet, stats)
- [ ] Web UI: panel budzetu tokenow na /status

### 2. Siec gosc Fritz!Box (odlozone - czeka na zakup IoT)
- [ ] Siec gosc wlaczona (izolacja IoT)
- [ ] Test komunikacji Maria <-> IoT przez sieci

### 3. Consciousness - osobowosc
- [ ] Self-model w semantic_graph (osobowosc)
- [ ] Pamiec rozmow z kondensacja
- [ ] Ciaglosc tozsamosci (birth date, uptime)
- [ ] SLEEP z "snami"

### 4. Vision - percepcja wizualna
- [ ] **Faza 1:** Sensor Abstraction Layer
- [ ] **Faza 2:** Preprocessing Layer
- [ ] **Faza 3:** Vision Modules (motion, scene, OCR, face)
- [ ] **Faza 4:** Vision Cortex + Attention

### 5. Smart Home
- [ ] Implementacja `agent_core/smart_home/`
- [ ] REPL commands `/device`, `/devices`
- [ ] Integracja z Vision

### 6. Inne
- [ ] Test dlugookresowy 8h+ na mini PC
- [ ] Fritz!Box: WireGuard z laptopa (nie tylko telefon)

## Konta na mini PC
| User | Rola | sudo |
|------|------|------|
| maria | Aplikacja | NIE |
| deployadmin | Admin | TAK |

## Przydatne komendy

```bash
# Status serwisow (jako deployadmin):
sudo systemctl status maria-ui ollama

# Logi Web UI:
sudo journalctl -u maria-ui -f

# Restart po zmianach w kodzie:
sudo systemctl restart maria-ui

# Testy (jako maria):
cd ~/maria && source venv/bin/activate
python -m pytest agent_core/tests/ -v

# Reczny backup:
bash ~/maria/scripts/backup.sh

# Test NIM API:
python -c "
from agent_core.llm.nim_client import NIMClient
from dotenv import load_dotenv; load_dotenv()
import os
c = NIMClient(api_key=os.environ['NVIDIA_NIM_API_KEY'], model='z-ai/glm5')
print(c.health_check())
"

# Sprawdz budzet tokenow:
python -c "
from agent_core.llm.token_budget import TokenBudget
b = TokenBudget()
print(b.get_status_text())
"
```
