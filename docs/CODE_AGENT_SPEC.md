# Code Agent - Specyfikacja Architektury

> **Data utworzenia:** 2026-02-01
> **Status:** Planowanie

## Cel

Zewnętrzny agent kodujący dla M.A.R.I.A. - modułowy system do zlecania zadań programistycznych z pełną izolacją i human-in-the-loop przed zatwierdzeniem.

## Hardware & Infrastruktura

| Komponent | Specyfikacja |
|-----------|--------------|
| **Urządzenie** | Mini PC, 64GB RAM |
| **Połączenie** | LAN/WiFi (kabel + backup) |
| **Storage** | Dysk zewnętrzny z mirror repo |
| **LLM** | CodeLlama 13B / DeepSeek Coder 6.7B (wymienialny) |
| **Sandbox** | Docker na mini PC |

## Kluczowa zasada

**Model LLM jest wymienialny** - tak jak Ollama w Marii. System musi być niezależny od konkretnego modelu.

## Architektura

```
M.A.R.I.A. (główny host)              Mini PC (Code Agent)
┌─────────────────────────┐           ┌─────────────────────────┐
│  agent_core/            │           │  code_agent/            │
│  ├── coding/            │  HTTP     │  ├── api_server.py      │
│  │   ├── client.py ─────┼──────────►│  ├── task_executor.py   │
│  │   ├── task_builder.py│           │  ├── sandbox/           │
│  │   └── review.py      │◄──────────┼  │   └── docker_runner.py│
│  └── homeostasis/       │  Response │  ├── llm_coder.py       │
│      (istniejący)       │           │  └── repo_mirror/       │
└─────────────────────────┘           └─────────────────────────┘
```

## Przepływ pracy

1. **Maria wykrywa potrzebę** (nowy moduł, bug, refaktor)
2. **Maria formułuje zlecenie** (używa Ollama do zaprojektowania prompta)
3. **Wysyła task do Code Agent** (REST API)
4. **Code Agent koduje** (używa swojego LLM)
5. **Code Agent testuje w sandbox** (Docker)
6. **Zwraca kod + raport do Marii**
7. **Maria analizuje raport**
8. **Human-in-the-loop** - ja (użytkownik) podejmuję ostateczną decyzję
9. **Zatwierdzenie lub odrzucenie**

## Bezpieczeństwo

- **Sandbox Docker** - kod testowany w izolacji
- **Miękki limit anty-loop** - zapobieganie nieskończonym pętlom
- **Human-in-the-loop** - ostateczna decyzja przed merge do głównego repo
- **Mirror repo** - agent pracuje na kopii, nie na oryginale

## Protokół komunikacji

**Transport:** REST API (HTTP)

### Endpointy (do zaprojektowania)

```
POST /task          - zlecenie nowego zadania
GET  /task/{id}     - status zadania
GET  /task/{id}/result - wynik (kod + raport)
POST /task/{id}/cancel - anulowanie
GET  /health        - health check
GET  /models        - lista dostępnych modeli LLM
POST /models/switch - zmiana aktywnego modelu
```

### Format Task (do zaprojektowania)

```json
{
  "task_id": "uuid",
  "type": "new_module | bugfix | refactor | test",
  "description": "...",
  "context_files": ["path1", "path2"],
  "constraints": {...},
  "priority": 1-5
}
```

### Format Report (do zaprojektowania)

```json
{
  "task_id": "uuid",
  "status": "success | failed | partial",
  "code_files": [...],
  "test_results": {...},
  "sandbox_log": "...",
  "llm_model_used": "codellama:13b",
  "iterations": 3,
  "confidence": 0.85
}
```

## Przyszłe rozszerzenia

- [ ] Dostęp Marii do internetu (web search, dokumentacja)
- [ ] Wiele agentów kodujących równolegle
- [ ] Specjalizacja agentów (frontend, backend, testy)

## TODO

- [ ] Zaprojektować szczegółowy protokół API
- [ ] Zdefiniować format tasków
- [ ] Zdefiniować format raportów
- [ ] Stworzyć moduł `agent_core/coding/client.py`
- [ ] Stworzyć szkielet `code_agent/` na mini PC
- [ ] Konfiguracja Docker sandbox

---

*Dokument roboczy - będzie rozwijany*
