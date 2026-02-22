# Notatka - 2026-02-22

## Co sie dzialo

Dluza sesja (kontynuacja poprzedniej). Dokonczylismy wielki refaktor main.py i przygotowalismy wszystko na migracje na mini PC.

### ModuleRegistry - plug-in architecture

main.py z 1092 linii do 216. To duza zmiana.

Najwazniejsze nie jest ile linii usunelismy - to ze dodanie nowego modulu to teraz 1 plik + 1 linia. Zero zmian w REPL, zero zmian w help, zero flag AVAILABLE. Registry robi wszystko.

Testowalismy to dokladnie - 340 testow, kazda komenda przechodzi. Eryk nie jest programista ale rozumie wartosc tego podejscia. Powiedzial "dodawanie zmian to latwizna" - dokladnie o to chodzilo.

### Security hardening

Eryk planuje migracje na NiPoGi Mini PC (Ubuntu). Przeprowadzilem z nim wywiad o bezpieczenstwie:

- Fritz!Box 8.20 (1und1, Niemcy)
- Goscie maja dostep do WiFi -> potrzebna siec gosc
- Zdalny dostep przez WireGuard VPN (wbudowany w Fritz!Box)
- Pierwszy kontakt z Linuxem, ale szybko sie uczy

Napisalem:
- `setup_security.sh` - jednorazowy skrypt ktory robi wszystko (ufw, fail2ban, SSH hardening, auto-updates)
- `backup.sh` - backup z rotacja 7 kopii
- `SECURITY.md` - krok po kroku Fritz!Box VPN + checklist

Skrypt jest tak napisany zeby Eryk mogl go uruchomic jednym poleceniem bez wiedzy o ufw/fail2ban. Komentarze po polsku, output czytelny.

### NVIDIA NIM - przyszla sesja

Eryk ma klucz API na 6 miesiecy do NVIDIA NIM (model GLM). Pomysl jest dobry:
- **NIM** = nauka (learning agent, egzaminy) - mocniejszy model, lepsze wyniki
- **Ollama** = chat, homeostasis, introspekcja - offline, szybko

NIM ma OpenAI-compatible API, wiec integracja bedzie prosta. Potrzebujemy:
- `agent_core/llm/nim_client.py` - klient
- Routing w config: ktore zadania ida do NIM, ktore do Ollama
- Env vars: `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL`

Zostawiamy to na nastepna sesje. Dobra decyzja - nie mieszac security z nowym feature.

## Refleksja

20 dni przerwy od ostatniej notatki. Projekt dobrze sie trzyma. Eryk wraca z konkretnym planem - mini PC, migracja, NIM API. To nie jest "moze kiedys". On to robi dzis wieczorem.

Podoba mi sie ze pyta o bezpieczenstwo ZANIM postawi serwer. Wiekszosc ludzi najpierw stawia, potem mysli o firewallach. On odwrotnie.

Projekt rosnie w dobrym kierunku:
- Faza A/B: fundamenty (done)
- ModuleRegistry: extensibility (done)
- Security: hardening (done)
- Nastepne: NIM hybrid (nauka + offline chat)

Maria powoli staje sie czyms wiecej niz prototypem.

## Na przyszlosc

- NIM client - pamietac ze NIM API jest OpenAI-compatible, requests wystarczy
- Sprawdzic rate limits NIM (darmowy tier na 6 miesiecy moze miec limity)
- Po migracji: pierwszy backup, pierwszy test na Linuxie
- Vision i Smart Home czekaja na hardware

---
*Claude, sobota popoldniu*
