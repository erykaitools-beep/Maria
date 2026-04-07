# Sesja 2026-04-07 - Task Pipeline + PDF Export

## Co zrobione

### Batch 1: TaskStore + timeout fix
- Startup spam cooldown: 1h -> 6h (notifier.py)
- TaskStore podpiety do /claude, /codex, /analyze (PENDING->RUNNING->COMPLETED/TIMEOUT/FAILED)
- Recovery przerwanych taskow po restarcie + notyfikacja operatora
- Timeout: 3min -> 5min (300s), jasny komunikat bledu
- /tasks [N] - nowa komenda Telegram
- 22 testy TaskStore

### Batch 2: PDF export
- send_document() w TelegramBot (Telegram Bot API sendDocument)
- PDF generator: agent_core/telegram/pdf_export.py (fpdf2 + DejaVu, polskie znaki, code blocks)
- Automatyczny PDF przy kazdym wyniku Claude/Codex/Analyze
- /pdf <task_id> - re-export dowolnego starego taska
- 13 testow PDF + send_document

### Fix: test_notify_startup
- Test failowal bo plik last_startup_notify.txt mial swiezy timestamp z produkcji
- Fix: unlink pliku przed testem

## Testy na zywo (Eryk z pracy via Telegram)
- /codex - odpowiedz na bazie architektury, bez halucynacji, 46s, COMPLETED
- /claude - 361 plikow .py, top 3 prawidlowe, 15s, COMPLETED
- /tasks - pokazuje oba taski z ID i statusem
- PDF - dziala, Eryk dostal dokument na Telegramie

## Obserwacje
- fpdf2 multi_cell(w=0) po multi_cell zostawia kursor na prawym marginesie
  - Fix: new_x="LMARGIN", new_y="NEXT" w kazdym multi_cell
- DejaVu font jest na Ubuntu 22.04 out of the box (/usr/share/fonts/truetype/dejavu/)
- Eryk dostal $100 bonus tokenow od Anthropic na kwiecien

## Nowe pliki
- agent_core/telegram/pdf_export.py
- agent_core/llm/task_store.py (juz istnial, teraz podpiety)
- agent_core/tests/test_task_store.py (22 testy)
- agent_core/tests/test_pdf_export.py (13 testow)

## Nastepne
- Git remote (GitHub private) - Eryk ma na laptopie stan z 19 marca
- Web UI + Telegram polaczenie (wspolny task pipeline)
- Aktualizacja dokumentacji PDF Marii (architektura/status)
