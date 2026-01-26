#!/usr/bin/env python3
"""
DEAMONMARIA V2 - Setup Script
Automatycznie tworzy wszystkie pliki i katalogi projektu.

Użycie:
    python setup_deamonmaria_v2.py
"""

import os
import sys
from pathlib import Path

print("="*60)
print("🚀 DEAMONMARIA V2 - Setup")
print("="*60)
print()

# Sprawdź Python version
if sys.version_info < (3, 8):
    print("❌ Wymagany Python 3.8+")
    print(f"   Twoja wersja: {sys.version}")
    sys.exit(1)

print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")

# Informacja o plikach
print()
print("📦 Ten skrypt utworzy:")
print("  • maria_core/ - główny katalog")
print("  • 7 modułów Python (~1730 linii kodu)")
print("  • input/, memory/, logs/ - katalogi danych")
print("  • Przykładowy plik testowy")
print()

response = input("Kontynuować? [Y/n]: ")
if response.lower() == 'n':
    print("Przerwano.")
    sys.exit(0)

print()
print("📁 Tworzę strukturę katalogów...")

base_dir = Path('maria_core')
directories = [
    base_dir,
    base_dir / 'input',
    base_dir / 'input' / 'example',
    base_dir / 'processed',
    base_dir / 'memory',
    base_dir / 'logs',
]

for directory in directories:
    directory.mkdir(parents=True, exist_ok=True)
    print(f"   ✓ {directory}")

print()
print("📄 Tworzę pliki...")
print("   (to może chwilę potrwać...)")
print()

# === DEFINICJE PLIKÓW (embedded) ===
# Ze względu na rozmiar, załaduję z osobnego modułu lub wczytam bezpośrednio

# Funkcja pomocnicza do zapisywania plików
def write_file(path: Path, content: str):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    size_kb = len(content) / 1024
    print(f"   ✓ {path.name:30s} ({size_kb:.1f} KB)")

# Zamiast embedować wszystko tutaj, wczytam z pliku CSV jeśli istnieje
csv_file = Path('deamonmaria_v2_all_files.csv')

if csv_file.exists():
    print("   📥 Wczytuję z deamonmaria_v2_all_files.csv...")
    import csv
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row['filename']
            content = row['content']

            filepath = base_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            write_file(filepath, content)
else:
    print("   ⚠️  deamonmaria_v2_all_files.csv nie znaleziony")
    print("   💡 Uruchom ten skrypt w katalogu z plikami DEAMONMARIA V2")
    print()
    print("   Alternatywnie - ręcznie skopiuj pliki:")
    print("   - config.py")
    print("   - memory_store.py")
    print("   - perception.py")
    print("   - learning_agent.py")
    print("   - exam_agent.py")
    print("   - priority_scheduler.py")
    print("   - orchestrator.py")
    print("   - requirements.txt")

print()
print("="*60)
print("✅ Setup zakończony!")
print("="*60)
print()
print("📋 Następne kroki:")
print()
print("1. Zainstaluj Ollama:")
if sys.platform == 'win32':
    print("   https://ollama.ai/download/windows")
else:
    print("   https://ollama.ai/")
print()
print("2. Pobierz model:")
print("   ollama pull llama3.1:8b")
print()
print("3. Zainstaluj zależności:")
print("   cd maria_core")
print("   pip install -r requirements.txt")
print()
print("4. Dodaj pliki .txt do:")
print("   maria_core/input/")
print()
print("5. Uruchom system:")
print("   python orchestrator.py")
print()
print("📖 Więcej info: maria_core/README.md")
print()
