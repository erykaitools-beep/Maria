#!/bin/bash
# =============================================================================
# M.A.R.I.A. - Backup Script
# =============================================================================
# Tworzy backup pamieci i konfiguracji Marii.
#
# Uzycie:
#   bash /home/maria/maria/scripts/backup.sh           # backup do ~/maria_backups/
#   bash /home/maria/maria/scripts/backup.sh /media/usb # backup na USB
#
# Co kopiuje:
#   - memory/          (pamiec dlugoterminowa, wyniki egzaminow)
#   - meta_data/       (model kodu, logi homeostazy)
#   - input/           (pliki wejsciowe do nauki)
#   - semantic_graph.json  (graf semantyczny)
#   - maria_learned_concepts.json (nauczone koncepcje)
#   - .env             (konfiguracja - zaszyfrowana opcjonalnie)
#
# Automatyczny backup (cron):
#   crontab -e
#   0 3 * * * /home/maria/maria/scripts/backup.sh >> /home/maria/maria/logs/backup.log 2>&1
# =============================================================================

set -e

# Konfiguracja
MARIA_DIR="/home/maria/maria"
BACKUP_ROOT="${1:-/mnt/storage/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/maria_backup_$TIMESTAMP"
MAX_BACKUPS=30  # ile backupow trzymac (starsze kasowane) - duzy dysk

# Kolory
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo "============================================="
echo "  M.A.R.I.A. - Backup"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================="
echo ""

# Sprawdz czy katalog zrodlowy istnieje
if [ ! -d "$MARIA_DIR" ]; then
    echo "[BLAD] Katalog $MARIA_DIR nie istnieje"
    exit 1
fi

# Utworz katalog backupu
mkdir -p "$BACKUP_DIR"

# --- Kopiowanie danych ---

# Pamiec (najwazniejsze!)
if [ -d "$MARIA_DIR/memory" ]; then
    cp -r "$MARIA_DIR/memory" "$BACKUP_DIR/"
    info "memory/ (pamiec dlugoterminowa)"
fi

# Metadane (model kodu, logi homeostazy)
if [ -d "$MARIA_DIR/meta_data" ]; then
    cp -r "$MARIA_DIR/meta_data" "$BACKUP_DIR/"
    info "meta_data/"
fi

# Pliki wejsciowe
if [ -d "$MARIA_DIR/input" ]; then
    cp -r "$MARIA_DIR/input" "$BACKUP_DIR/"
    info "input/"
fi

# Graf semantyczny
if [ -f "$MARIA_DIR/semantic_graph.json" ]; then
    cp "$MARIA_DIR/semantic_graph.json" "$BACKUP_DIR/"
    info "semantic_graph.json"
fi

# Nauczone koncepcje
if [ -f "$MARIA_DIR/maria_learned_concepts.json" ]; then
    cp "$MARIA_DIR/maria_learned_concepts.json" "$BACKUP_DIR/"
    info "maria_learned_concepts.json"
fi

# Konfiguracja (bez sekretow w nazwie)
if [ -f "$MARIA_DIR/.env" ]; then
    cp "$MARIA_DIR/.env" "$BACKUP_DIR/env_backup"
    chmod 600 "$BACKUP_DIR/env_backup"
    info ".env (zapisany jako env_backup, chmod 600)"
fi

# --- Kompresja ---
cd "$BACKUP_ROOT"
tar -czf "maria_backup_$TIMESTAMP.tar.gz" "maria_backup_$TIMESTAMP/" 2>/dev/null
rm -rf "$BACKUP_DIR"
info "Skompresowano -> maria_backup_$TIMESTAMP.tar.gz"

# --- Rozmiar ---
BACKUP_SIZE=$(du -sh "$BACKUP_ROOT/maria_backup_$TIMESTAMP.tar.gz" | cut -f1)
info "Rozmiar: $BACKUP_SIZE"

# --- Rotacja (usun stare backupy) ---
BACKUP_COUNT=$(ls -1 "$BACKUP_ROOT"/maria_backup_*.tar.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
    ls -1t "$BACKUP_ROOT"/maria_backup_*.tar.gz | tail -n "$REMOVE_COUNT" | xargs rm -f
    warn "Usunieto $REMOVE_COUNT starych backupow (limit: $MAX_BACKUPS)"
fi

echo ""
echo "============================================="
info "Backup gotowy: $BACKUP_ROOT/maria_backup_$TIMESTAMP.tar.gz"
echo "  Backupow na dysku: $(ls -1 "$BACKUP_ROOT"/maria_backup_*.tar.gz 2>/dev/null | wc -l)/$MAX_BACKUPS"
echo "============================================="
