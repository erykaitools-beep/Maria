# M.A.R.I.A. — Portfolio für AI Engineering

[Projektübersicht](../README.md) · [Technische Fallstudie](production-reliability-case-study.md)
· [Nachweisprüfung](evidence/portfolio-audit-2026-10-26.md) · [Bestehende Demo](demo/2026-10-22/README.md)

## Projektprofil

M.A.R.I.A. ist eine in Python entwickelte Agentenlaufzeit für einen dauerhaft
betriebenen persönlichen Assistenten. Sie verbindet lokale Sprachmodelle,
persistenten Gesprächskontext, regelbasierte Aktionsplanung und nachvollziehbare
Ausführung. Die Installation läuft auf einem Ryzen-5-7430U-MiniPC mit einer
32-GB-RAM-Konfiguration und integrierter Grafik. Eine dedizierte GPU wurde bei
der Bestandsaufnahme nicht erkannt.

Das Projekt adressiert praktische Betriebsprobleme: blockierte Modellanfragen,
begrenzten Speicher, unterbrochene Aufgaben und widersprüchliche Statussignale.
Es ist eine persönliche Installation mit öffentlich prüfbarem Quellcode und
Tests. Hochverfügbarkeit, allgemeine Problemlösefähigkeit und fehlerfreie
Autonomie werden nicht behauptet. Entwicklung und Fehleranalyse erfolgen mit
Unterstützung von KI-Werkzeugen; die Verantwortung für Anforderungen,
Integration, Entscheidungen und Prüfung bleibt beim Projektverantwortlichen.

## Fünf technische Kompetenzen

1. **Python-Systementwicklung:** zustandsbehaftete Dienste, Threads, geregelte
   Hintergrundarbeit, Fehlerbehandlung und Lebenszyklusverwaltung.
2. **Applied AI und Modellintegration:** Ollama, konfigurierbare Modellrollen,
   Embedding-Suche sowie die Abwägung von Qualität, Speicherbedarf und Latenz.
3. **Agentensysteme und Automatisierung:** Ziele, Aktionsrichtlinien,
   begrenzte Wiederholungen, explizite Delegation und gespeicherte Ergebnisse.
4. **Zuverlässigkeit und Diagnose:** getrennte Aufrufer- und HTTP-Zeitlimits,
   unabhängiger Watchdog, Ressourcenbegrenzung und korrelierte Ablaufspuren.
5. **Testen und Evidenzbewertung:** pytest, JavaScript-Protokolltests,
   Regressionstests für Ausfälle und klare Trennung zwischen Simulation,
   Integrationstest und tatsächlicher Betriebsbeobachtung.

## Fünf überprüfte Ergebnisse

1. Der öffentliche CI-Lauf vom **22. Oktober 2026** meldet je Python-Version
   3.10, 3.11 und 3.12 **8.164 bestandene Tests**, vier übersprungene Tests,
   einen unerwartet bestandenen Test und 140 bestandene Untertests.
   Wiederholungen der Versionsmatrix werden nicht zusammengezählt.
2. Der getrennte CI-Pfad für den lokalen Chat besteht **24 Tests und
   16 Untertests** mit einem simulierten Ollama-Server. Das prüft die
   Integration, nicht die Qualität eines realen Sprachmodells.
3. Die Host-Prüfung vom **26. Oktober 2026** bestätigt
   `MemoryHigh=16G` und `MemoryMax=20G` durch systemd und die zugehörigen
   cgroup-Werte. Diese Grenzen betreffen den Maria-Dienst und sind keine
   pauschale Begrenzung aller Prozesse oder externer Modelldienste.
4. Der Quellcode begrenzt den aktuellen Belief-Bestand auf **2.000** und den
   Vektorspeicher auf **10.000** Einträge. Das sind Aufbewahrungsgrenzen,
   keine behaupteten aktuellen Bestandszahlen oder Qualitätswerte.
5. Die bestehende Demo dokumentiert **einen abgeschlossenen Auftrag mit zwei
   Dateien** und eine Ergebnisabfrage ohne neuen Auftrag. Die erzeugte CSV
   enthält nur die Kopfzeile; der menschliche Spieltest steht noch aus.

## Ein prägender Betriebsfehler

Ein Workflow-Schritt wartete innerhalb des zentralen Takts auf eine externe
Analyse. Dadurch blockierte dieselbe Anfrage auch Statusverarbeitung, Planung
und Nachrichtenabfrage. Die Ursache lag im Ausführungsmodell: langsame Arbeit
lief auf dem Thread, der die übrigen Komponenten koordinieren sollte.

Die Korrektur verlagert den Schritt in einen Hintergrundthread und verhindert
überlappende Ausführungen. Ein Regressionstest prüft ausdrücklich den Aufruf aus
dem echten Tick-Pfad. Die verbleibende Grenze ist genauso wichtig: Der Takt
bleibt ansprechbar, aber ein blockierter Worker kann weiterhin den Workflow
anhalten. Reaktionsfähigkeit und erfolgreicher Abschluss müssen getrennt
beobachtet werden. Diese Unterscheidung lässt sich unmittelbar auf betriebliche
AI-Automatisierungen übertragen.

## Textbaustein für den Lebenslauf

**M.A.R.I.A. — Eigenprojekt, Python / Agentic Systems / AI Automation**
Entwicklung und Betrieb einer zustandsbehafteten Agentenlaufzeit mit lokalen
Ollama-Modellen, persistentem Kontext, Aktionsrichtlinien und nachvollziehbaren
Ergebnissen. Schwerpunkt auf Ressourcensteuerung, Fehlerdiagnose und
Wiederanlauf nach Störungen auf einem MiniPC. Öffentliche CI mit 8.164
bestandenen Tests je Python-Version; dokumentierte Regressionstests für
blockierende Modellaufrufe, Workflow-Ausführung und Speicherpflege.
KI-gestützte Entwicklung mit eigener Anforderungs- und Integrationsverantwortung.

## Textbaustein für LinkedIn

Mit M.A.R.I.A. entwickle ich einen Python-basierten Assistenten, dessen Zustand
über einzelne Modellaufrufe hinaus erhalten bleibt. Mich interessiert besonders,
wie Agentensysteme unter realen Ressourcen- und Betriebsgrenzen funktionieren:
Welche Arbeit darf laufen, woran erkenne ich Stillstand, und wie bleibt ein
Ergebnis nach einem Neustart nachvollziehbar?

Das öffentliche Repository zeigt Architektur, Tests und konkrete Fehleranalysen.
Die vorhandene Demo verbindet eine Anfrage mit gespeicherten Projektdateien;
dafür werden zusätzliche Kritaqo-/Codex-Integrationen verwendet. Der lokale
Chat ist separat startbar. Mein Schwerpunkt liegt auf anwendbarem AI Engineering,
prüfbaren Automatisierungen und verständlich dokumentierten Grenzen.
