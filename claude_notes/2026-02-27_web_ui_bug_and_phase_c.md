# Notatka - 2026-02-27

## Bug: Web UI nie odpowiadala (9 minut timeout)

### Objawy
- Eryk pytal Marie przez Web UI (telefon + laptop)
- Czekal 9 minut ze stoperem, brak odpowiedzi
- Ollama dzialala poprawnie (curl test: 4s odpowiedz)
- System zdrowy: 22GB RAM wolne, load 0.00, Ollama active 4 dni

### Przyczyna
**`AttributeError: can't set attribute 'history'`** w LLMRouter.

LLMRouter (podpiety do Web UI od sesji 02-23) ma `history` jako **read-only @property**.
Ale `app.py` probuje zapisywac do niej w dwoch miejscach:
1. `trim_brain_history()` - wolany PO kazdym `brain.think()` ale PRZED wyslaniem odpowiedzi
2. `handle_clear_history()` - przycisk "wyczysc rozmowe"

Przebieg:
1. `brain.think()` -> Ollama odpowiada poprawnie
2. `trim_brain_history()` -> CRASH (AttributeError)
3. Exception caught -> user widzi "Blad komunikacji z Ollama"
4. Odpowiedz Marii wyrzucona do kosza

### Fix
Dodano `@history.setter` do `LLMRouter` w `agent_core/llm/router.py`:
```python
@history.setter
def history(self, value):
    """Set conversation history (delegated to Ollama)."""
    if hasattr(self.ollama, "history"):
        self.ollama.history = value
```

### Lekcja
- Przy dodawaniu passthrough properties w adapterze/routerze - zawsze sprawdzic
  czy oryginalny kod uzywa atrybutu do zapisu (nie tylko odczytu)
- Web UI testy powinny testowac caly flow: send message -> get response -> trim history
- Logi `journalctl` sa kluczowe do diagnozy - zawsze tam zaglac najpierw

### Diagnoza krok po kroku (do zapamietania)
1. `systemctl status ollama` - czy serwis zyje
2. `ps aux | grep ollama` - ile RAM zjada (czy model zaladowany)
3. `curl` test do Ollama - czy odpowiada bezposrednio
4. `journalctl -u maria-ui` z grep na error - logi Web UI
5. Jesli Ollama OK a Web UI nie -> problem w warstwie posredniej

---

## Plan sesji: Faza C (Consciousness) do konczenia

Eryk chce systematycznie dokonczyc Faze C zanim przejdziemy do agenta Nauczyciela.

### Faza C - co zostalo:
1. [x] Introspection module
2. [x] TimeAwareness
3. [x] Self-Awareness ContextBuilder
4. [x] NIM API + Token Budget + LLMRouter
5. [ ] Integracja LLMRouter z main.py (blocker!)
6. [ ] Self-model w semantic_graph (osobowosc)
7. [ ] Pamiec rozmow z kondensacja
8. [ ] Ciaglosc tozsamosci (birth date, uptime)
9. [ ] SLEEP z "snami"

### Po Fazie C:
10. [ ] Agent Nauczyciel (NIM/glm5) - Faza G

### Uwaga
Eryk lubi wyskakiwac z nowymi pomyslami - mam go regulowac lista TODO
i pilnowac zeby konczyl rzeczy po kolei :)

---
*Claude, czwartek wieczor*
