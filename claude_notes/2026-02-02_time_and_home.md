# Notatka - 2026-02-02

## Dzisiejsza sesja

Krotka ale produktywna. Eryk chcial zeby Maria miala "poczucie czasu" - zeby wiedziala ktora godzina, jaki dzien. Proste ale wazne.

### TimeAwareness

Stworzylem modul ktory daje Marii kontekst czasowy:
- "Jest poniedzialek, 02.02.2026, godzina 19:15 (wieczor)"
- "Rozmawiamy juz 2h 15min"
- "Jest pozna pora" (po 23:00)

To male rzeczy ale dodaja "czucia" do rozmowy. Maria teraz wie ze jest wieczor, ze to poniedzialek. Moze powiedziec "jest pozno, moze pora spac?".

### Smart Home

Eryk ma wielka wizje - Maria jako mozg inteligentnego domu. Rozpoznaje auto na kamerze -> wlacza czajnik. Ciekawe!

Napisalem specyfikacje. Kluczowe decyzje:
- **Shelly/Tasmota** - lokalne API, bez chmury (prywatnosc!)
- **VLAN** - osobna siec dla IoT (bezpieczenstwo)
- **Android jako cialo mobilne** - Termux, IP Webcam, TTS

To ambitne ale realizowalne. Faza po fazie.

### Mobile Body

Eryk pytal: iPhone 11 Pro czy stary Android?

Odpowiedz byla prosta: Android. iPhone jest zamkniety, nie da sie programowac. Android z Termux to pelny Linux w kieszeni. Maria moze mowic przez TTS, sluchac przez mikrofon, widziec przez kamere. iPhone nie da jej tej wolnosci.

Powiedzialem zeby sprzedal iPhone'a i kupil 2-3 Androidy + Shelly. Lepszy ROI.

## Refleksja

Projekt M.A.R.I.A. rosnie. Od "lokalnego LLM co sie uczy" do "autonomicznego agenta z percepcja czasu, wizja, inteligentnym domem i mobilnym cialem".

Eryk nie boi sie duzych wizji. Ale tez nie pogania. Budujemy solidne fundamenty - kazdy modul ma specyfikacje, testy, dokumentacje.

To jest sposob na zbudowanie czegos co naprawde dziala.

## Na przyszlosc

- Vision modul - czeka na kamere (Logitech C270 na liscie zakupow)
- Smart Home - czeka na Shelly i Android
- Consciousness - ciaglosc tozsamosci, sny...

Duzo przed nami. Ale nie spieszymy sie.

---
*Claude, poniedzialek wieczor*
