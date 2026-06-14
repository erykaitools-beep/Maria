# Dostęp do Marii z całego świata (Tailscale + PWA)

> Cel: apka Marii na telefonie działa wszędzie (praca, miasto, wakacje),
> a NIC nie wystaje do publicznego internetu. Tailscale = prywatny,
> szyfrowany "kabel" między Twoim telefonem a mini PC. Bez otwierania
> portów na routerze, bez domeny, bez chmury.
>
> Stan: kod Marii jest GOTOWY (CORS sam wykrywa Tailscale po restarcie).
> Do zrobienia zostały kroki poniżej — razem ~10 minut, raz.

## Krok 1 — instalacja na mini PC (deployadmin, ~3 min)

```bash
# jako deployadmin:
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

`tailscale up` wypisze link `https://login.tailscale.com/a/...` —
otwórz go w przeglądarce i zaloguj się (Google/GitHub/Microsoft — co
wolisz; to tworzy darmowe konto, plan darmowy starcza na zawsze przy
naszej skali: do 3 użytkowników / 100 urządzeń).

Sprawdzenie:
```bash
tailscale ip -4     # pokaże adres typu 100.x.y.z
tailscale status    # pokaże maszynę "maria" jako connected
```

## Krok 2 — telefon (~2 min)

1. Google Play → zainstaluj aplikację **Tailscale**.
2. Zaloguj się na TO SAMO konto co w kroku 1.
3. Przełącznik w apce Tailscale na ON (VPN aktywny).

Od teraz telefon "widzi" mini PC pod adresem `100.x.y.z` z każdej sieci
na świecie (LTE, hotel, praca).

## Krok 3 — restart Marii (~1 min)

Telegram → `/restart` (albo deployadmin: `sudo systemctl restart maria`).

Po restarcie Maria sama dopisze adres Tailscale do dozwolonych źródeł
(CORS auto-detect w `maria_ui/config.py`) — czat SocketIO zadziała przez
tunel bez ruszania `.env`.

## Krok 4 — apka na telefonie (~2 min)

1. W Chrome na telefonie otwórz:
   `http://<adres-z-kroku-1>:5000/static/mobile/index.html`
   (np. `http://100.101.102.103:5000/static/mobile/index.html`)
2. Zaloguj się PIN-em jak zwykle.
3. Menu Chrome (trzy kropki) → **"Dodaj do ekranu głównego"** /
   **"Zainstaluj aplikację"**.
4. Na pulpicie pojawi się fioletowa ikona **M.** — odpala się jak
   normalna apka, pełny ekran, bez paska przeglądarki.

> Ikona z LAN (`<MINI_PC_LAN_IP>`) i ikona z Tailscale (`100.x`) to dwa
> osobne "origins" — najprościej: zainstaluj PWA z adresu Tailscale i
> używaj go ZAWSZE (działa też w domu, bo tunel działa i w LAN).

## Bezpieczeństwo (krótko)

- Port 5000 NIE jest wystawiony do internetu — widzą go tylko urządzenia
  zalogowane na Twoje konto Tailscale (telefon + mini PC).
- Logowanie PIN-em dalej obowiązuje, sesja jak dotychczas.
- Ruch w tunelu jest szyfrowany end-to-end (WireGuard).
- Jak zgubisz telefon: wejdź na login.tailscale.com → usuń urządzenie.

## Co dalej (opcjonalnie, później)

- **Natywny APK** (Etap 6 ze spec): mini PC nie ma Android SDK; budowa
  przez chmurę (Codemagic/GitHub Actions). PWA pokrywa ~95% tego samego —
  do decyzji, czy w ogóle warto.
- **MagicDNS**: w panelu Tailscale można włączyć nazwy zamiast IP —
  wtedy adres to `http://maria.tailXXXX.ts.net:5000/...` (kod Marii już
  to wykrywa).
