# Budowa — co teraz na placu

> Czyta to zakladka "Budowa" w apce mobilnej (endpoint /api/build).
> Aktualizowane przez Claude na koniec kazdej sesji. Format: trzy sekcje
> ponizej, zwykly tekst, po polsku, krotko (1-3 zdania na sekcje).

## Teraz

Tor syntezy (Maria sama laczy wiedze z wielu zrodel) zostal WZMOCNIONY i jest
ZYWY. Ultra-audyt znalazl 22 dziury (egzamin sprawdzal recall samej syntezy a
nie prawdy; synteza mogla karmic sie wlasnym wyjsciem; observe kasowal artefakt).
5 cegiel: widocznosc (/synthreview), hamulec echo-komnaty, cap (synteza =
OBSERVATION nie FACT), sanityzacja zrodel, bramka WIERNOSCI (lokalny qwen3
sprawdza czy synteza trzyma sie zrodel PRZED zapisem). **ZWERYFIKOWANE NA ZYWO
06-13:** synteza "uczenie maszynowe" przeszla bramke 6/6 poparte, egzamin 0.675,
would_promote=True (observe → discard). Pelny artefakt widoczny w /synthreview.

## Ostatnio skonczone

2026-06-13 (noc): Hardening toru syntezy do GO. 5 cegiel, ~556 linii kodu +
~470 testow (57 syntheza + 12 belief-cap + 2 synthreview, wszystko zielone;
682 w calym promieniu razenia). Bramka wiernosci (cegla 5): lokalny qwen3
ocenia kazde twierdzenie syntezy wzgledem zrodel jako POPARTE/NIEWYPOWIEDZIANE/
SPRZECZNE i odrzuca halucynacje PRZED egzaminem (omija jego koszt). Cap (cegla
3): zsyntetyzowane przekonania ladaja jako OBSERVATION nie FACT — nawet zla
synteza nie jest juz prawie-nieusuwalnym faktem. Raport audytu:
claude_notes/2026-06-13_synthesis_audit_raw.json.

## Nastepny krok

1) Obserwujemy z REALNYM sygnalem: /synthreview pokazuje co Maria
syntetyzuje, co bramka lapie, co przechodzi. Zbieramy pare dni danych
(autonomiczny picker strzela 1x/dzien w oknie nauki). Pod obserwacja
TEZ kalibracja sedziego: czy bramka czasem ODRZUCA (nie tylko przepuszcza).
2) Decyzja go/no-go na SYNTH_ENABLED=1 po paru dniach.
3) Opcjonalnie przed uzbrojeniem (operacyjne, nizszy priorytet bo cap juz
chroni): dzienny limit promocji + auto-powrot-do-observe gdy operator
oflaguje zla synteze. Uwaga: cykl ~8 min (qwen3 sedzia na CPU ~350s).
