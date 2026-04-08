# 2026-03-29 - Capability Router + CDL v2

## Co zrobilem

### Capability/Task Router (agent_core/routing/)
- CapabilitySpec (frozen dataclass): name, description, required_subsystems, k7_classification, tags
- CapabilityRouter: register/dispatch/discover/get_k7_classification
- 13 handler factories (closure-based, 1:1 z ActionExecutor._exec_*)
- Late-binding Telegram notifier (lambda on executor._telegram_notifier)
- Dual-path: router dispatch gdy dostepny, legacy if/elif fallback
- K7 classify_action() opcjonalnie z routera
- Wired in homeostasis_module.py (13 capabilities registered at startup)
- 63 testy

### CDL v2
- Chat feedback: user widzi "Zaczynam nauke: X" w chacie po wykryciu intencji
- Dedup: nie tworzy duplikatu jesli aktywny cel na ten sam temat istnieje
- Goal cancellation: detect_cancel_intent() - 8 PL + 3 EN wzorcow
  - "zapomnij o nauce X", "anuluj nauke X", "nie ucz sie o X"
  - "przestan uczyc o X", "olej temat X", "zrezygnuj z nauki o X"
  - "cancel learning X", "stop learning X", "forget about X"
- Web UI chat.js: obsługa learning_detected, learning_cancelled, learning_cancel_notfound, already_active
- 12 nowych testow

### Web UI polish
- CSS: --mo-text-md: 0.85rem, --mo-r-xl: 18px, .mo-btn--sm (padding+font)
- /api/capabilities endpoint (CapabilityRouter specs, static fallback)

## Testy
- Start sesji: 2491
- Po CapabilityRouter: 2554 (+63)
- Po CDL v2: 2566 (+12)

## 2 commity
- `dcc4fed` - CapabilityRouter (1777 lines, 10 files)
- `dc68a8c` - CDL v2 + Web UI polish (245 lines, 6 files)

## Nastepna sesja
- **Agent Krytyk** - nowy agent wskazujacy luki w wiedzy (Faza G)
- Phase C cleanup (opcjonalnie) - usuniecie legacy if/elif z ActionExecutor
- Po restarcie Maria zobaczy CapabilityRouter w logach: "[Homeostasis] [OK] CapabilityRouter wired (13 capabilities)"
