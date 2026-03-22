# OpenClaw Setup - Blocker (2026-03-21)

## Stan
- OpenClaw 2026.3.13 zainstalowany (npm install -g openclaw)
- Gateway service dziala (systemd, port 18789, loopback)
- Token: skonfigurowany w gateway.auth.token
- Config: tools.profile=full, tools.exec.ask=off, model=ollama/llama3.1:8b
- Token dodany do /home/maria/maria/.env jako OPENCLAW_GATEWAY_TOKEN

## Blocker
`POST /tools/invoke` zwraca `"Tool not available: exec"` bo:
1. Gateway to relay - potrzebuje podlaczonego agenta (via WebSocket) ktory udostepnia tools
2. Agent nie startuje - blad: "No API key found for provider ollama"
3. OpenClaw nie rozpoznaje lokalnej Ollama bez API key (Ollama nie uzywa kluczy)

## Co probowalem
- `openclaw config set tools.profile full` - nie pomoglo (gateway nie ma toolsow bez agenta)
- `openclaw config set gateway.tools.allow [...]` - jak wyzej
- `echo '{"ollama":{"apiKey":"ollama","baseUrl":"http://localhost:11434"}}' > auth-profiles.json` - zly format
- `OLLAMA_API_KEY=ollama openclaw agent --local --session-id main --message "echo hello" --json` - zawisl, brak odpowiedzi

## Root cause (znalezione pod koniec sesji)
- Auth naprawiony: `OLLAMA_API_KEY=ollama` env var dziala
- Agent probuje uzyc llama3.1:8b ale Maria go blokuje (concurrent access)
- Tools sa dostepne (widac w system prompt raporcie: exec, read, write, browser, web_fetch itd.)
- Ale agent timeout 600s bo Ollama zajeta przez Marie

## Plan na nastepna sesje: MODEL SEPARATION
1. `ollama pull qwen2.5:3b` - maly model dla OpenClaw agenta (2-3GB RAM)
2. `openclaw config set agents.defaults.model.primary ollama/qwen2.5:3b` - OpenClaw uzywa malego modelu
3. Maria dalej na llama3.1:8b - zero zmian
4. Coexistence: 5GB (Maria) + 2GB (OpenClaw) = 7GB - bezpieczne na 32GB RAM
5. Uruchom OpenClaw agent w tmux z OLLAMA_API_KEY=ollama
6. Test HTTP tools/invoke -> powinno dzialac
7. Restart Maria -> `[Homeostasis] [OK] OpenClaw effector wired`

## Eryk's vision: pelny multi-model routing
- Kazdy model (Maria, OpenClaw, przyszle) w ModelScheduler REGISTRY
- ModelScheduler koordynuje kto kiedy uzywa Ollama
- Logowanie uzycia modeli (ktory model, kto wywolal, latency)
- Powiazane z Model Registry Stage 2 (benchmark MODEL-04 triage)

## Konfiguracja na mini PC
- Gateway config: /home/deployadmin/.openclaw/openclaw.json
- Agent dir: /home/deployadmin/.openclaw/agents/main/agent/
- Auth profiles: /home/deployadmin/.openclaw/agents/main/agent/auth-profiles.json
- Logi: /tmp/openclaw/openclaw-2026-03-21.log
- Maria .env: /home/maria/maria/.env (OPENCLAW_GATEWAY_TOKEN dodany)

## Wazne
- Klient OpenClaw w agent_core/effector/ jest GOTOWY i przetestowany (47 testow)
- Maria dziala normalnie bez OpenClaw (graceful fallback)
- Trzeba tylko ustawic auth Ollama w OpenClaw -> agent startuje -> tools dostepne -> Maria podlacza sie automatycznie
