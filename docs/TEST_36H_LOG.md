# M.A.R.I.A. - Log Testu 36h

> **Data startu:** _______________
> **Operator:** _______________

---

## Baseline (przed startem)

| Metryka | Wartość |
|---------|---------|
| Data/godzina startu | |
| RAM used (MB) | |
| RAM total (MB) | |
| CPU % | |
| Węzły w grafie | |
| Epizody | |
| Pliki w input/ | |

---

## Checkpointy

### Checkpoint 1h

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes | |
| RAM used (MB) | |
| Węzły w grafie | |
| Epizody | |
| Uwagi | |

---

### Checkpoint 3h

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| Węzły w grafie | |
| Epizody | |
| Uwagi | |

---

### Checkpoint 6h

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| Węzły w grafie | |
| Epizody | |
| Trend RAM | ↑ / → / ↓ |
| Uwagi | |

---

### Checkpoint 12h (POŁOWA)

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes (total) | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| RAM delta od startu | |
| Węzły w grafie | |
| Węzły delta | |
| Epizody | |
| Epizody delta | |
| Wykonany test obciążenia? | TAK / NIE |
| Wynik testu obciążenia | |
| Uwagi | |

---

### Checkpoint 18h

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes (total) | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| Węzły w grafie | |
| Epizody | |
| Trend ogólny | STABILNY / DEGRADACJA / POPRAWA |
| Uwagi | |

---

### Checkpoint 24h (DOBA)

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes (total) | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| RAM delta od startu | |
| Peak RAM w ciągu 24h | |
| Węzły w grafie | |
| Epizody | |
| Najdłuższy okres w ACTIVE | |
| Czas w REDUCED | |
| Czas w SLEEP | |
| Czy był SURVIVAL | TAK / NIE |
| Wykonany test idle? | TAK / NIE |
| Wynik testu idle | |
| Uwagi | |

---

### Checkpoint 30h

| Metryka | Wartość |
|---------|---------|
| Godzina | |
| Tryb homeostasis | |
| Health score | |
| Mode changes (total) | |
| Alerts (C/A/W) | |
| RAM used (MB) | |
| Węzły w grafie | |
| Epizody | |
| Uwagi | |

---

### Checkpoint 36h (KONIEC)

| Metryka | Wartość |
|---------|---------|
| Godzina zakończenia | |
| Rzeczywisty czas testu | |
| Tryb homeostasis | |
| Health score | |
| Mode changes (total) | |
| Alerts CRITICAL | |
| Alerts ALERT | |
| Alerts WARNING | |
| RAM start | |
| RAM koniec | |
| RAM delta | |
| RAM peak | |
| Węzły start | |
| Węzły koniec | |
| Węzły delta | |
| Epizody start | |
| Epizody koniec | |
| Epizody delta | |

---

## Incydenty

| Godzina | Opis | Akcja podjęta | Wynik |
|---------|------|---------------|-------|
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |

---

## Testy scenariuszowe

### Test obciążenia pamięci

| Aspekt | Wartość |
|--------|---------|
| Godzina testu | |
| RAM przed | |
| Akcja | Otwarto: _____________ |
| Reakcja homeostasis | |
| Przejście do REDUCED? | TAK / NIE |
| Czas w REDUCED | |
| Powrót do ACTIVE? | TAK / NIE |
| RAM po | |
| Ocena | OK / PROBLEM |

### Test uczenia (/learn)

| Aspekt | Wartość |
|--------|---------|
| Godzina testu | |
| Komenda | /learn _____ |
| Czy ukończono? | TAK / NIE |
| Nowe węzły | |
| Reakcja homeostasis | |
| Ocena | OK / PROBLEM |

### Test idle (brak interakcji)

| Aspekt | Wartość |
|--------|---------|
| Godzina startu idle | |
| Godzina sprawdzenia | |
| Czas idle | |
| Przejście do SLEEP? | TAK / NIE |
| Czas do SLEEP | |
| Wybudzenie po interakcji? | TAK / NIE |
| Czas wybudzenia | |
| Ocena | OK / PROBLEM |

---

## Podsumowanie końcowe

### Statystyki

| Metryka | Wartość |
|---------|---------|
| Całkowity czas testu | h |
| Procent czasu w ACTIVE | % |
| Procent czasu w REDUCED | % |
| Procent czasu w SLEEP | % |
| Procent czasu w SURVIVAL | % |
| Średni health score | |
| Minimalny health score | |
| Przyrost węzłów | |
| Przyrost epizodów | |
| Memory leak (MB/h) | |

### Ocena

| Kryterium | Ocena (1-5) | Komentarz |
|-----------|-------------|-----------|
| Stabilność | | |
| Reakcja na obciążenie | | |
| Recovery po problemach | | |
| Efektywność uczenia | | |
| Zarządzanie pamięcią | | |
| **OGÓLNA OCENA** | **/5** | |

### Wnioski

1.

2.

3.

### Rekomendacje na przyszłość

1.

2.

3.

---

## Załączniki

- [ ] Zrzut `/homeostasis events 100` na końcu testu
- [ ] Zrzut `/homeostasis summary` na końcu testu
- [ ] Backup `meta_data/homeostasis_events.jsonl`
- [ ] Backup `memory/*.jsonl`
- [ ] Zrzut ekranu Task Manager (RAM usage)

---

*Test zakończony: _______________*
*Podpis: _______________*
