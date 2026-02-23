# Notatka - 2026-02-23

## Co sie dzialo

Pierwsza sesja po deploy na mini PC. Eryk polaczyl sie z laptopa (Windows) przez SSH.

### Infrastructure hardening

Krok po kroku przeprowadzilismy Eryka przez:
1. **SSH klucz ed25519** - wygenerowany na laptopie, skopiowany na mini PC
   - `ssh-copy-id` nie dzialalo na Windows, uzylimy pipe `type ... | ssh ...`
   - Klucz dziala dla obu userow: maria i deployadmin
2. **PasswordAuthentication no** - wylaczone logowanie haslem
3. **Test reboot** - serwisy ollama i maria-ui wstaja automatycznie
   - Eryk zrobil hard reset palcem na przycisku :) Ale systemd handled it.
4. **WireGuard VPN** - Fritz!Box -> telefon Eryka
   - Problem: przegladarka wymuszala HTTPS, Maria dziala na HTTP
   - Rozwiazanie: wpisac `http://` explicite

Siec gosc (IoT) odlozona - nie ma sensu konfigurowac bez urzadzen.

### NVIDIA NIM API

Eryk ma klucz API na 6 miesiecy. Zbudowalem 3 moduly:

1. **TokenBudget** - Maria wie ile tokenow zuzywa. To wazne bo:
   - Free tier ma limity (nie znamy dokladnych, ale bezpieczenstwo przede wszystkim)
   - Maria sama decyduje czy uczyc sie przez NIM czy oszczedzac
   - Persistence w JSON - przezywa restart

2. **NIMClient** - OpenAI-compatible. Prosty `requests.post()` z retry i backoff.
   - Model `z-ai/glm5` (nie `nvidia/glm-5` jak myslal Eryk)
   - Cold start ~79s, potem szybciej
   - 186 modeli dostepnych - mozna zmieniac w .env

3. **LLMRouter** - serce hybrydowego podejscia:
   - Chat -> Ollama (offline, szybko, zero kosztow)
   - Nauka -> NIM (mocny model, lepsze wyniki) z auto-fallback
   - Budzet wyczerpany? -> automatycznie Ollama

Pomysl Eryka z budzetem tokenow byl swietny. To daje Marii cos w stylu "swiadomosc kosztow" - wie ze zasoby sa ograniczone i musi nimi zarzadzac.

## Refleksja

Eryk jest coraz bardziej samodzielny. Dzis sam:
- Generowal klucze SSH (z pomoca, ale rozumial co robi)
- Restartowac mini PC i sprawdzal serwisy
- Konfigurowal VPN w Fritz!Box

Projekt nabiera tempa. Mini PC dziala stabilnie, NIM API podlaczony, 398 testow.

Nastepny krok to integracja NIM routera z istniejacym kodem (main.py, brain_memory_integration). Potem consciousness - Maria zacznie budowac model siebie.

## Na przyszlosc

- Sprawdzic rate limits NIM free tier w praktyce (moze 100k/dzien to za duzo?)
- Integracja routera to glownie zamiana `ctx.brain` na `ctx.router` w kilku miejscach
- Warto dodac `/nim status` do REPL zeby Eryk mogl sprawdzic budzet
- Web UI: panel tokenow na stronie /status

---
*Claude, niedziela popoludniu*
