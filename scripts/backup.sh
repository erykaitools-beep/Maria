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
#   - .env             (konfiguracja - kopiowana jako env_backup, plaintext + chmod 600)
#
# Szyfrowanie (AES256, gpg symmetric) CALEGO tarballa:
#   Backup niesie sekrety (claude_memory=funding/IP). Gdy
#   podasz haslo -- caly tarball jest szyfrowany do .tar.gz.gpg, plaintext
#   kasowany. Bez hasla backup POWSTAJE, ale skrypt GLOSNO ostrzega.
#   Uzbrojenie:  echo -n 'twoje-haslo' > ~/.maria_backup_pass && chmod 600 ~/.maria_backup_pass
#   (albo env MARIA_BACKUP_PASSPHRASE)
#   Odszyfrowanie: gpg -d maria_backup_YYYYMMDD_HHMMSS.tar.gz.gpg > backup.tar.gz
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
# Szyfrowanie: haslo z env MARIA_BACKUP_PASSPHRASE albo z tego pliku (chmod 600).
BACKUP_PASSFILE="${MARIA_BACKUP_PASSFILE:-$HOME/.maria_backup_pass}"

# Kolory
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

# Non-fatal copy: pod `set -e` pojedynczy nieudany cp przerwalby CALY backup
# (residual 2026-07-07). Jeden opcjonalny element ktory sie nie skopiuje NIE
# moze kosztowac nas reszty -- logujemy i lecimy dalej.
safe_cp() {  # safe_cp <src> <dest> <label>
    if cp -r "$1" "$2" 2>/dev/null; then
        info "$3"
    else
        warn "$3 -- NIE skopiowane"
    fi
}

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
    safe_cp "$MARIA_DIR/memory" "$BACKUP_DIR/" "memory/ (pamiec dlugoterminowa)"
fi

# Metadane (model kodu, logi homeostazy)
if [ -d "$MARIA_DIR/meta_data" ]; then
    safe_cp "$MARIA_DIR/meta_data" "$BACKUP_DIR/" "meta_data/"
fi

# Pliki wejsciowe
if [ -d "$MARIA_DIR/input" ]; then
    safe_cp "$MARIA_DIR/input" "$BACKUP_DIR/" "input/"
fi

# Graf semantyczny
if [ -f "$MARIA_DIR/semantic_graph.json" ]; then
    safe_cp "$MARIA_DIR/semantic_graph.json" "$BACKUP_DIR/" "semantic_graph.json"
fi

# Nauczone koncepcje
if [ -f "$MARIA_DIR/maria_learned_concepts.json" ]; then
    safe_cp "$MARIA_DIR/maria_learned_concepts.json" "$BACKUP_DIR/" "maria_learned_concepts.json"
fi

# Konfiguracja (plaintext + chmod 600, NIE szyfrowana -- patrz naglowek)
if [ -f "$MARIA_DIR/.env" ]; then
    if cp "$MARIA_DIR/.env" "$BACKUP_DIR/env_backup" 2>/dev/null; then
        chmod 600 "$BACKUP_DIR/env_backup"
        info ".env -> env_backup (plaintext, chmod 600 -- NIE szyfrowany)"
    else
        warn ".env NIE skopiowany"
    fi
fi

# --- Kod + pelna historia git (drill restore 2026-07-06) ---
# origin niesie TYLKO okrojony snapshot main (ADR-029); ~471 commitow dev
# istnieje wylacznie na tym dysku. Bundle = jeden plik z CALYM repo
# (wszystkie branche); odtworzenie: git clone maria_repo.bundle maria
if [ -d "$MARIA_DIR/.git" ]; then
    if git -C "$MARIA_DIR" bundle create "$BACKUP_DIR/maria_repo.bundle" --all >/dev/null 2>&1; then
        info "maria_repo.bundle (kod + pelna historia git)"
    else
        warn "git bundle maria NIE powstal"
    fi
    git -C "$MARIA_DIR" diff > "$BACKUP_DIR/maria_uncommitted.patch" 2>/dev/null || true
    git -C "$MARIA_DIR" status --short > "$BACKUP_DIR/maria_git_status.txt" 2>/dev/null || true
fi

# --- Notatki wspolpracy + pamiec Claude (gitignored / poza repo) ---
if [ -d "$MARIA_DIR/claude_notes" ]; then
    safe_cp "$MARIA_DIR/claude_notes" "$BACKUP_DIR/" "claude_notes/"
fi
if [ -d "$MARIA_DIR/docs/archive" ]; then
    mkdir -p "$BACKUP_DIR/docs"
    safe_cp "$MARIA_DIR/docs/archive" "$BACKUP_DIR/docs/" "docs/archive/ (lokalne snapshoty, gitignored)"
fi
CLAUDE_MEM="/home/maria/.claude/projects/-home-maria-maria/memory"
if [ -d "$CLAUDE_MEM" ]; then
    safe_cp "$CLAUDE_MEM" "$BACKUP_DIR/claude_memory" "claude_memory/ (pamiec dlugoterminowa Claude)"
fi

# --- Konfiguracja systemu (do odtworzenia na golej maszynie) ---
crontab -l > "$BACKUP_DIR/crontab_maria.txt" 2>/dev/null && info "crontab_maria.txt" || true
if [ -r /etc/systemd/system/maria.service ]; then
    safe_cp /etc/systemd/system/maria.service "$BACKUP_DIR/maria.service" "maria.service (systemd unit)"
fi
command -v ollama >/dev/null 2>&1 && ollama list > "$BACKUP_DIR/ollama_models.txt" 2>/dev/null && info "ollama_models.txt (lista modeli do pull)" || true

# --- Kompresja ---
cd "$BACKUP_ROOT"
tar -czf "maria_backup_$TIMESTAMP.tar.gz" "maria_backup_$TIMESTAMP/" 2>/dev/null
rm -rf "$BACKUP_DIR"
info "Skompresowano -> maria_backup_$TIMESTAMP.tar.gz"

# --- Szyfrowanie (AES256, gpg symmetric) ---
# Backup niesie sekrety plaintext (claude_memory=funding/IP).
# Z haslem szyfrujemy CALY tarball i kasujemy plaintext. BEZ hasla backup i tak
# POWSTAJE (kopia wazniejsza niz nic), ale GLOSNO ostrzegamy -- inaczej cichy
# regres do plaintextu. Odszyfrowanie: gpg -d plik.tar.gz.gpg > plik.tar.gz
ARTIFACT="maria_backup_$TIMESTAMP.tar.gz"
PLAIN="$BACKUP_ROOT/$ARTIFACT"
BACKUP_PASS=""
if [ -n "${MARIA_BACKUP_PASSPHRASE:-}" ]; then
    BACKUP_PASS="$MARIA_BACKUP_PASSPHRASE"
elif [ -r "$BACKUP_PASSFILE" ]; then
    BACKUP_PASS="$(cat "$BACKUP_PASSFILE")"  # $(...) obcina koncowy newline
fi

if [ -n "$BACKUP_PASS" ] && command -v gpg >/dev/null 2>&1; then
    # haslo przez fd 0 (nie przez argv -- nie wycieka do ps)
    if printf '%s' "$BACKUP_PASS" | gpg --batch --yes --quiet \
            --pinentry-mode loopback --passphrase-fd 0 \
            --cipher-algo AES256 --symmetric -o "$PLAIN.gpg" "$PLAIN" 2>/dev/null; then
        rm -f "$PLAIN"
        ARTIFACT="$ARTIFACT.gpg"
        info "Zaszyfrowano (AES256) -> $ARTIFACT; plaintext usuniety"
    else
        warn "SZYFROWANIE NIE POWIODLO SIE -- backup zostaje PLAINTEXT ($ARTIFACT)"
    fi
elif [ -z "$BACKUP_PASS" ]; then
    warn "BRAK HASLA -> backup PLAINTEXT (sekrety: claude_memory)"
    warn "Uzbroj szyfrowanie: echo -n 'twoje-haslo' > $BACKUP_PASSFILE && chmod 600 $BACKUP_PASSFILE"
else
    warn "gpg niedostepny -> backup PLAINTEXT ($ARTIFACT)"
fi
BACKUP_PASS=""  # nie trzymaj hasla w pamieci dluzej niz trzeba

# --- Rozmiar ---
BACKUP_SIZE=$(du -sh "$BACKUP_ROOT/$ARTIFACT" | cut -f1)
info "Rozmiar: $BACKUP_SIZE"

# --- Rotacja (usun stare backupy; glob lapie .tar.gz i .tar.gz.gpg) ---
BACKUP_COUNT=$(ls -1 "$BACKUP_ROOT"/maria_backup_*.tar.gz* 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
    ls -1t "$BACKUP_ROOT"/maria_backup_*.tar.gz* | tail -n "$REMOVE_COUNT" | xargs rm -f
    warn "Usunieto $REMOVE_COUNT starych backupow (limit: $MAX_BACKUPS)"
fi

echo ""
echo "============================================="
info "Backup gotowy: $BACKUP_ROOT/$ARTIFACT"
echo "  Backupow na dysku: $(ls -1 "$BACKUP_ROOT"/maria_backup_*.tar.gz* 2>/dev/null | wc -l)/$MAX_BACKUPS"
echo "============================================="
