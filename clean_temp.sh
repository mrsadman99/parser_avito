#!/bin/sh
# Очистка временных файлов парсера Avito.
#
# Удаляет по умолчанию:
#   logs/*.log*      — логи (app.log и ротации)
#   storage/*.json   — кэши (cookies, сконвертированные URL, старые AI-кэши)
#   __pycache__/     — Python-байткод по всему проекту (кроме venv)
#
# По флагам:
#   --results        — также удалить result/*.xlsx
#   --db             — также удалить database.db (сброс истории просмотренных)
#
# По умолчанию — dry-run. Для реального удаления добавьте --yes.
#
# Примеры:
#   sh clean_temp.sh
#   sh clean_temp.sh --yes
#   sh clean_temp.sh --yes --results --db

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

YES=0
RESULTS=0
DB=0

usage() {
    echo "Очистка временных файлов парсера Avito"
    echo "Использование: sh $(basename "$0") [--yes] [--results] [--db]"
    echo "  --yes      реально удалить (по умолчанию dry-run)"
    echo "  --results  также удалить result/*.xlsx"
    echo "  --db       также удалить database.db"
}

for arg in "$@"; do
    case "$arg" in
        -y|--yes) YES=1 ;;
        --results) RESULTS=1 ;;
        --db) DB=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Неизвестный аргумент: $arg" >&2; exit 1 ;;
    esac
done

collect() {
    find logs -maxdepth 1 -type f -name '*.log*' 2>/dev/null
    find storage -maxdepth 1 -type f -name '*.json' 2>/dev/null
    if [ "$RESULTS" = 1 ]; then
        find result -maxdepth 1 -type f -name '*.xlsx' 2>/dev/null
    fi
    if [ "$DB" = 1 ] && [ -f database.db ]; then
        echo database.db
    fi
    find . \( -name venv -o -name .venv \) -prune -o -type d -name __pycache__ -print 2>/dev/null \
        | sed 's|^\./||'
}

LIST="$(collect)"

if [ -z "$LIST" ]; then
    echo "Временные файлы не найдены."
    exit 0
fi

echo "Найдено для удаления:"
printf '%s\n' "$LIST" | sed 's/^/  /'

if [ "$YES" != 1 ]; then
    echo ""
    echo "Dry-run: ничего не удалено. Для удаления запустите с --yes."
    exit 0
fi

printf '%s\n' "$LIST" | while IFS= read -r path; do
    [ -n "$path" ] || continue
    if [ -d "$path" ]; then
        rm -rf "$path"
    elif [ -f "$path" ]; then
        rm -f "$path"
    fi
done

echo ""
echo "Готово. Временные файлы удалены."
