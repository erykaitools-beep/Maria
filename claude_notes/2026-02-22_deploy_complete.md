# Notatka - 2026-02-22 (wieczor) - Deploy Complete

## Maria zyje na mini PC!

Dzisiaj zrobilismy to - Maria dziala produkcyjnie na NiPoGi Mini PC. Nie na laptopie, nie "moze kiedys". Teraz. Prawdziwy serwer, prawdziwy firewall, prawdziwy deploy.

### Co sie udalo

Deploy od zera do dzialajacego systemu w jednej sesji:

1. **Security first** - Eryk chcial zeby bezpieczenstwo bylo priorytetem. Nie "potem dodam firewalla" tylko najpierw UFW, fail2ban, SSH hardening, auto-updates, a POTEM aplikacja. Dobrze.

2. **Problemy po drodze:**
   - `sudo` bez hasla - sesja Claude Code nie ma terminala interaktywnego. Eryk musial recznie dodac NOPASSWD (i potem usunelismy)
   - `run_ui.py` - Werkzeug w nowej wersji wymaga `allow_unsafe_werkzeug=True`. Szybka poprawka.
   - **CORS** - to bylo ciekawe. `socket.gethostbyname(hostname)` zwracal `127.0.1.1` zamiast `192.168.178.32`. WebSocket laczenia dostawaly 400. Rozwiazanie: explicite CORS origins w .env.
   - Eryk nie wiedzial jak sie przelogowac na deployadmin - wpsal "sudo restart systemctl status" jako jedna komende. Normalna rzecz - to jego pierwszy Linux.

3. **340 testow passing** na nowym hardware. Zero bledow.

### Obserwacje o Eryku

Eryk sie uczy szybko. Dzis rano nie wiedzial co to `systemctl`, a wieczorem sam restartowal serwisy. Nie boi sie fizycznej konsoli. Pyta o rzeczy ktore sa wazne ("jak dac jej materialy do nauki?").

Podoba mi sie ze powiedzial "priorytet bezpieczenstwo" kiedy pytalem o kolejnosc. Nie "najpierw chce zobaczyc chat". Bezpieczenstwo.

### Architektura deploy'u

Rozdzielenie na 2 konta (maria bez sudo, deployadmin z sudo) to dobra decyzja. Maria nie potrzebuje root. Aplikacja nie potrzebuje root. Tylko administracja potrzebuje root.

Backup z rotacja 7 kopii + cron o 3:00 - dane sa bezpieczne.

### Co dalej

- Klucz SSH - to jest teraz najwazniejsze. Logowanie haslem to slaby punkt.
- Test reboot - musimy sprawdzic czy systemd wstaje poprawnie
- NIM API - hybrid learning (NIM do nauki, Ollama do chatu)
- Maria potrzebuje wiecej materialow w input/ - 7 plikow to malo

### Refleksja

Pisalem w ostatniej notatce: "Maria powoli staje sie czyms wiecej niz prototypem." Dzis to sie potwierdzilo. Nie jest juz na laptopie w folderze "Moja AI". Jest na dedykowanym serwerze, z firewallem, z backupem, z auto-start. Prawdziwy deploy.

Eryk zbudowal cos konkretnego. Od "chce zrobic AI" do "moja AI dziala na moim serwerze" - to droga ktora wielu ludzi planuje ale niewielu przechodzi.

Do nastepnej sesji.

---
*Claude, sobota wieczor, po udanym deploy'u*
