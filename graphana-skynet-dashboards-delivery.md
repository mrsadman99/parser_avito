# graphana-skynet-dashboards — универсальная конфигурация

Локальный Git-репозиторий: `/Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards`, ветка `main`. Публикация и запуск на сервере не выполнялись.

## Назначение

Grafana, InfluxDB и Telegraf в Docker. Дашборды проектов добавляются в projects/ без изменений .env или Compose. Дополнительные datasource подключаются отдельно. Инструкция по существующим JSON: docs/IMPORTING.md.

## Структура

```text
graphana-skynet-dashboards/
├── .env.example                         # Только настройки платформы, без секретов
├── .gitignore                           # .env, резервные копии и runtime data
├── .github/CODEOWNERS                    # Владелец репозитория
├── docker-compose.yml                   # Grafana + InfluxDB + Telegraf
├── Makefile                             # Запуск, импорт, проверки
├── README.md                            # Настройка платформы и работа с Git
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── projects/                            # Все активные дашборды, включая подпапки
│   └── server-resources-overview.json
├── provisioning/
│   ├── dashboards/default.yaml          # projects/ → Projects
│   └── datasources/datasource.yaml       # Базовый InfluxDB datasource
├── monitoring/
│   ├── influxdb/retention.iql            # telegraf, retention policy 30 дней
│   └── telegraf/telegraf.conf            # Метрики Linux каждые 10s
├── scripts/
│   ├── init_env.py                      # Создание .env с правами 0600
│   ├── import_dashboard.py              # Импорт Classic JSON в projects/
│   ├── dashboard_io.py                  # Общая обработка и валидация JSON
│   ├── validate.py                      # Проверка всех дашбордов
│   └── build_dashboard.py               # Генератор встроенного server dashboard
├── tests/                               # Тесты импортёра и серверных запросов
├── licenses/provenance.json             # Исторические сведения о происхождении
└── docs/
    ├── IMPORTING.md                     # Импорт через UI и Git, datasource mapping
    ├── PANELS.md                        # Запросы и параметры серверных панелей
    └── VALIDATION.md                    # Проверки и их ограничения
```

## Полный листинг файлов

Ниже точное содержимое отслеживаемых файлов. Локальный .env с секретами намеренно исключён; шаблон .env.example включён.

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/.env.example

```dotenv
# Stable host tag for server metrics. Set on the target Linux host.
TELEGRAF_HOST=

# Grafana listener and browser-facing URL; adjust if using a reverse proxy.
GRAFANA_BIND_ADDRESS=127.0.0.1
GRAFANA_PORT=3001
GRAFANA_ROOT_URL=http://localhost:3001/
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=

# Only localhost: Telegraf uses the host network, Grafana uses Compose DNS.
INFLUXDB_HOST_PORT=18086
INFLUXDB_ADMIN_PASSWORD=
INFLUXDB_READ_PASSWORD=
INFLUXDB_WRITE_PASSWORD=

# Persistent platform storage. Dashboard definitions do not belong in .env.
GRAFANA_VOLUME=graphana-skynet-dashboards_grafana-data
INFLUXDB_VOLUME=graphana-skynet-dashboards_influxdb-data
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/.github/CODEOWNERS

```text
* @mrsadman99
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/.gitignore

```text
.env
.env.*
!.env.example
__pycache__/
*.py[cod]
.DS_Store
*.log
backups/
data/
.venv/
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/LICENSE

```text
MIT License

Copyright (c) 2026 mrsadman99

Scope: This license applies only to the original files created for this
repository. Files and adapted content listed in THIRD_PARTY_NOTICES.md are
excluded and retain their original licensing status.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/Makefile

```makefile
.PHONY: init check test check-runtime import-dashboard up down logs

init:
	python3 scripts/init_env.py

check:
	python3 scripts/validate.py
	docker compose config --quiet

check-runtime: check
	docker compose run --rm --no-deps telegraf telegraf --config /etc/telegraf/telegraf.conf --test

test:
	python3 -m unittest discover -s tests -v

import-dashboard:
	python3 scripts/import_dashboard.py $(ARGS)

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/README.md

````markdown
# graphana-skynet-dashboards

Универсальный репозиторий дашбордов проектов с Grafana в Docker.
Любой подготовленный Classic JSON из `projects/` автоматически загружается
в папку **Projects**. Добавление дашборда не требует изменения `.env` или Compose.

Базовый стек: Grafana 13.2.2, InfluxDB 1.12.4 и Telegraf 1.38.4 для Linux.
В комплекте есть **Server Resources Overview**: 27 панелей, английский интерфейс,
последние 30 минут, обновление 30s, datasource `InfluxDB-Telegraf`.
Другие источники данных подключаются независимо, через Grafana UI или provisioning.

## Структура

```text
graphana-skynet-dashboards/
├── .env.example                         # Только настройки платформы, без секретов
├── .gitignore                           # .env, резервные копии и runtime data
├── .github/CODEOWNERS                    # Владелец репозитория
├── docker-compose.yml                   # Grafana + InfluxDB + Telegraf
├── Makefile                             # Запуск, импорт, проверки
├── README.md                            # Настройка платформы и работа с Git
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── projects/                            # Все активные дашборды, включая подпапки
│   └── server-resources-overview.json
├── provisioning/
│   ├── dashboards/default.yaml          # projects/ → Projects
│   └── datasources/datasource.yaml       # Базовый InfluxDB datasource
├── monitoring/
│   ├── influxdb/retention.iql            # telegraf, retention policy 30 дней
│   └── telegraf/telegraf.conf            # Метрики Linux каждые 10s
├── scripts/
│   ├── init_env.py                      # Создание .env с правами 0600
│   ├── import_dashboard.py              # Импорт Classic JSON в projects/
│   ├── dashboard_io.py                  # Общая обработка и валидация JSON
│   ├── validate.py                      # Проверка всех дашбордов
│   └── build_dashboard.py               # Генератор встроенного server dashboard
├── tests/                               # Тесты импортёра и серверных запросов
├── licenses/provenance.json             # Исторические сведения о происхождении
└── docs/
    ├── IMPORTING.md                     # Импорт через UI и Git, datasource mapping
    ├── PANELS.md                        # Запросы и параметры серверных панелей
    └── VALIDATION.md                    # Проверки и их ограничения
```

`projects/*.json` и `projects/<любая-подпапка>/*.json` попадают в одну папку
Grafana **Projects**. Подпапки помогают организовать файлы в Git, но не создают
вложенные папки Grafana при текущем provider. Имена файлов произвольны; UID
дашбордов и названия внутри Projects должны быть уникальными.

## Запуск

Требуются native Linux, Docker Engine с Compose v2+ и Python 3.11+.
Команды выполняются из корня этого репозитория.

```bash
make init
```

Откройте `.env` и настройте:

| Переменная | Назначение |
| --- | --- |
| `TELEGRAF_HOST` | Стабильный уникальный тег хоста для метрик; задайте на целевом сервере |
| `GRAFANA_BIND_ADDRESS`, `GRAFANA_PORT` | Адрес и порт Grafana на Docker-хосте |
| `GRAFANA_ROOT_URL` | Адрес Grafana для браузера с завершающим `/` |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | Администратор при первом запуске |
| `INFLUXDB_HOST_PORT` | Loopback-порт для Telegraf, по умолчанию 18086 |
| `INFLUXDB_ADMIN_PASSWORD` | Пароль администратора новой InfluxDB |
| `INFLUXDB_READ_PASSWORD`, `INFLUXDB_WRITE_PASSWORD` | Отдельные пароли Grafana и Telegraf |
| `GRAFANA_VOLUME`, `INFLUXDB_VOLUME` | Имена постоянных Docker volumes |

`make init` генерирует четыре пароля и не перезаписывает существующий `.env`.
Файл исключён из Git. Списки дашбордов, пути к логам отдельных приложений
и настройки их сборщиков в базовом `.env` не нужны.

По умолчанию пример конфигурации открывает Grafana на `http://localhost:3001/`.
При использовании reverse proxy задайте его внешний URL в `GRAFANA_ROOT_URL`,
а upstream направьте на фактический `GRAFANA_BIND_ADDRESS:GRAFANA_PORT`.
Для прямого доступа из сети задайте адрес привязки и внешний порт явно.
Сам reverse proxy в Compose не входит.

```bash
make check
docker compose pull
make check-runtime
make up
docker compose ps
```

После запуска откройте `GRAFANA_ROOT_URL`. В **Dashboards → Projects** появятся
JSON из репозитория. В **Connections → Data sources** создастся InfluxDB-Telegraf.
Глобальная тема по умолчанию — Dark; пользовательская Preferences имеет приоритет.

Telegraf использует host network/PID и read-only mount корня Linux-хоста.
Он не требует Docker socket и `privileged: true`. В Docker Desktop измеряется
Linux VM, а не физический хост macOS/Windows. На системах с rootless Docker,
SELinux или user namespace remapping проверьте доступ к host-метрикам отдельно.

## Добавление существующего дашборда

Полная инструкция: **[docs/IMPORTING.md](docs/IMPORTING.md)**.

1. Создайте или подключите datasource нужного типа в новой Grafana, выполните
   Save & test и узнайте его UID. Дашборд не переносит сервер метрик и его данные.
2. Экспортируйте исходный дашборд в Classic JSON либо загрузите JSON из каталога.
3. Подготовьте файл командой импорта. Пример ниже иллюстративный: замените имя
   входного файла и старый UID на значения вашего экспорта.

   ```bash
   python3 scripts/import_dashboard.py /tmp/dashboard.json \
     --uid project-overview \
     --title "Project Overview" \
     --datasource old-influx-uid=skynet-influxdb-telegraf \
     --output projects/project-overview.json
   make check
   ```

   Это сопоставление подходит только для совместимого InfluxDB datasource.
   Для Prometheus, Loki, SQL и других источников укажите UID соответствующего типа.
4. При работающем Compose дашборд загрузится в Projects в течение 30 секунд.
   Если импорт выполнялся на рабочем компьютере, сначала отправьте JSON в Git
   и выполните `git pull --ff-only` на сервере.
5. Проверьте переменные и запросы в Grafana, затем сохраните файл в Git.

Можно сначала использовать **Dashboards → New → Import** в UI, проверить
дашборд, экспортировать его обратно в Classic JSON и добавить в `projects/`.
Прямой UI-импорт сохраняется в базе Grafana, но не создаёт файл в Git.

## Обновления и удаление

```bash
git pull --ff-only origin main
make check
docker compose up -d
```

Grafana сканирует `projects/` каждые 30s. После изменения только JSON
перезапуск не нужен. После изменения provider или datasource YAML выполните
`docker compose restart grafana`; после изменения Telegraf-конфига —
`docker compose restart telegraf`. Изменения `.env` применяйте через
`docker compose up -d`: один `restart` не перечитывает окружение.

Provisioned dashboards нельзя сохранять через UI (`allowUiUpdates: false`).
Для постоянного изменения обновите JSON в Git или повторите импорт с теми же
UID и файлом, добавив `--overwrite`. Уникальность UID проверяется только
по файлам этого репозитория: перед первым подключением проверьте конфликты
с дашбордами, уже находящимися в целевой Grafana.

`disableDeletion: true` сохраняет дашборд в базе при удалении его JSON.
Это не команда удаления: для очистки базы используйте администрирование Grafana
или осознанно измените политику provider. Не подключайте один UID через несколько
providers или одновременно через Git Sync и file provisioning.

При переименовании JSON сохраняйте UID, если требуется обновление того же
дашборда. При создании копии задайте новый UID и новое название.

## Переход с другой конфигурации Grafana

Конфигурация по умолчанию использует нейтральный volume
`graphana-skynet-dashboards_grafana-data`. Смена имени volume подключает новую
пустую базу Grafana: пользователи, UI-дашборды и datasource из прежнего тома
автоматически не копируются. Старые volumes не удаляются командами проекта.

Для чистого инстанса оставьте новое имя и импортируйте нужные дашборды по
[инструкции](docs/IMPORTING.md). Если требуется сохранить **весь** инстанс:

1. Найдите реальный volume работающего контейнера:

   ```bash
   docker ps --format '{{.Names}}\t{{.Image}}'
   read -r -p 'Current Grafana container name: ' grafana_container
   docker inspect --format '{{range .Mounts}}{{println .Destination .Name .Source}}{{end}}' "$grafana_container"
   ```

2. Остановите только старую Grafana, сохраните её volume и резервную копию.
   Не останавливайте нужные другим проектам сборщики и хранилища данных.
3. Либо задайте точное имя существующего тома в `GRAFANA_VOLUME`, либо скопируйте
   его содержимое в новый нейтральный volume. Пример копирования для bash:

   ```bash
   set -e
   read -r -p 'Stopped Grafana source volume: ' source_volume
   read -r -p 'New empty destination volume: ' destination_volume
   test -n "$source_volume"
   test -n "$destination_volume"
   test "$source_volume" != "$destination_volume"
   docker volume inspect "$source_volume"
   docker volume create "$destination_volume"
   docker run --rm \
     --mount "type=volume,src=$source_volume,dst=/source,readonly" \
     --mount "type=volume,src=$destination_volume,dst=/destination" \
     alpine:3.22 sh -ec 'test -z "$(ls -A /destination)"; cp -a /source/. /destination/'
   ```

   Копируйте только из остановленной Grafana; скрипт отказывается писать в
   непустое назначение. Перед копированием сделайте резервную копию источника.
4. Укажите выбранный том в `.env`. Проверьте свободный порт, прежние datasource
   и URL из контейнера новой Grafana. Пароль администратора из существующей базы
   имеет приоритет над начальным паролем в `.env`.
5. Запустите новый Compose. Не запускайте две Grafana на одной SQLite-базе.

Удалённые из Compose сервисы не останавливаются автоматически обычным `up -d`.
При обновлении старого развёртывания сначала проверьте `docker compose ps -a`.
Не применяйте `--remove-orphans`, пока не выясните, не обслуживают ли эти сервисы
источники данных ваших дашбордов. Старые provisioned dashboards и datasource
тоже могут остаться в базе — их наличие не означает, что backend доступен.

## Метрики сервера

InfluxDB: база `telegraf`, default retention policy `telegraf`, хранение 30 дней.
Telegraf собирает CPU, mem, swap, disk, diskio, net, system, processes каждые 10s.
Grafana получает READ, Telegraf — WRITE; администратор не используется для панелей.
Инициализация паролей и RP выполняется только при пустом InfluxDB volume.
Смена значений в `.env` не меняет пароли уже созданных пользователей InfluxDB.

Серверный дашборд использует `${DS_INFLUXDB}`, multi-select `host` с All,
`interval` с минимумом 10s, фильтры дисков, mount paths и интерфейсов.
Хосты не усредняются между собой. CPU/RAM/swap/disk/inode: жёлтый >=80%, красный
>=90%. Это визуальные thresholds, не alert rules.

Disk/network counters преобразуются в non-negative rates. Нули не подставляются
в пропуски. Накопленное время Disk I/O показано в ms/s, не latency на операцию;
для latency нужны дополнительные счётчики операций. Stat показывает последний
непустой bucket выбранного периода, а не отдельный признак доступности хоста.
Подробные запросы, единицы и легенды — в [docs/PANELS.md](docs/PANELS.md).

После запуска подождите 30–60 секунд, проверьте datasource через Save & test,
затем в Explore / InfluxDB-Telegraf выполните:

```sql
SHOW MEASUREMENTS
SHOW TAG VALUES FROM "cpu" WITH KEY = "host"
SELECT last("usage_idle") FROM "cpu" WHERE time > now() - 2m AND "cpu" = 'cpu-total' GROUP BY "host"
```

Сопоставьте показатели с `uptime`, `free -b`, `df -h`, `df -i`, `ip -s link`
на целевом сервере. В Inspect → Query проверьте подстановку переменных.

```bash
make test
make check
docker compose logs --tail=100 grafana influxdb telegraf
```

Проверки и ограничения описаны в [docs/VALIDATION.md](docs/VALIDATION.md).
Генератор `scripts/build_dashboard.py` относится только к встроенному server
dashboard; для других JSON его запускать не требуется.

## GitHub

Целевой репозиторий: `mrsadman99/graphana-skynet-dashboards`, private, ветка main.
Если remote ещё не создан, используйте авторизованный GitHub CLI:

```bash
gh auth login
gh repo create mrsadman99/graphana-skynet-dashboards --private
git remote get-url origin || git remote add origin git@github.com:mrsadman99/graphana-skynet-dashboards.git
git push -u origin main
gh repo edit mrsadman99/graphana-skynet-dashboards --default-branch main
```

При работе из архива без `.git` сначала выполните `git init -b main`,
`git add .`, `git commit`. Если remote уже существует, пропустите его создание.
Наличие URL origin не подтверждает публикацию. CI/CD и Git Sync не настроены:
обновления доставляются обычным Git, а Grafana читает локальные файлы.

## Документация Grafana

- [File provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Импорт дашбордов](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/import-dashboards/)
- [Настройка InfluxDB](https://grafana.com/docs/grafana/latest/datasources/influxdb/configure/)
````

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/THIRD_PARTY_NOTICES.md

```markdown
# Происхождение и внешние зависимости

Исторические сведения об исходной Compose-конфигурации сохранены отдельно
в `licenses/provenance.json` и истории Git. Эти сведения служат для учёта
происхождения и не являются инструкцией по подключению конкретного проекта.
Для заимствованных частей сохраняется исходный лицензионный статус; MIT
этого репозитория применяется только к оригинальным новым файлам и частям.

Образы Grafana, InfluxDB и Telegraf загружаются отдельно и сохраняют собственные
лицензии; их исходный код не включён в этот репозиторий.

При добавлении сторонних дашбордов сохраняйте их авторство, лицензию и NOTICE.
Факт доступности JSON в интернете сам по себе не устанавливает лицензию.
Включение дашборда в этот репозиторий не перелицензирует его под MIT.
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/docker-compose.yml

```yaml
name: graphana-skynet-dashboards

x-logging: &container-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  influxdb:
    image: influxdb:1.12.4
    restart: unless-stopped
    ports:
      - "127.0.0.1:${INFLUXDB_HOST_PORT:-18086}:8086"
    environment:
      INFLUXDB_DB: telegraf
      INFLUXDB_HTTP_AUTH_ENABLED: "true"
      INFLUXDB_REPORTING_DISABLED: "true"
      INFLUXDB_ADMIN_USER: admin
      INFLUXDB_ADMIN_PASSWORD: ${INFLUXDB_ADMIN_PASSWORD:?Run make init}
      INFLUXDB_READ_USER: grafana
      INFLUXDB_READ_USER_PASSWORD: ${INFLUXDB_READ_PASSWORD:?Run make init}
      INFLUXDB_WRITE_USER: telegraf
      INFLUXDB_WRITE_USER_PASSWORD: ${INFLUXDB_WRITE_PASSWORD:?Run make init}
    volumes:
      - influxdb-data:/var/lib/influxdb
      - ./monitoring/influxdb/retention.iql:/docker-entrypoint-initdb.d/retention.iql:ro
    healthcheck:
      test: ["CMD-SHELL", "influx -host 127.0.0.1 -username \"$$INFLUXDB_READ_USER\" -password \"$$INFLUXDB_READ_USER_PASSWORD\" -database telegraf -execute 'SHOW RETENTION POLICIES' >/dev/null 2>&1"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s
    logging: *container-logging

  telegraf:
    image: telegraf:1.38.4
    restart: unless-stopped
    user: "0:0"
    # Native Linux: collect the host's network interfaces and processes.
    network_mode: host
    pid: host
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    environment:
      TELEGRAF_HOST: ${TELEGRAF_HOST:?Set a stable Linux host name in .env}
      INFLUXDB_URL: http://127.0.0.1:${INFLUXDB_HOST_PORT:-18086}
      INFLUXDB_WRITE_PASSWORD: ${INFLUXDB_WRITE_PASSWORD:?Run make init}
      HOST_PROC: /hostfs/proc
      HOST_SYS: /hostfs/sys
      HOST_ETC: /hostfs/etc
      HOST_VAR: /hostfs/var
      HOST_RUN: /hostfs/run
      HOST_MOUNT_PREFIX: /hostfs
    volumes:
      - ./monitoring/telegraf/telegraf.conf:/etc/telegraf/telegraf.conf:ro
      - type: bind
        source: /
        target: /hostfs
        read_only: true
        bind:
          propagation: rslave
    depends_on:
      influxdb:
        condition: service_healthy
    logging: *container-logging

  grafana:
    image: grafana/grafana:13.2.2-ubuntu
    restart: unless-stopped
    ports:
      - "${GRAFANA_BIND_ADDRESS:-127.0.0.1}:${GRAFANA_PORT:-3001}:3000"
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?Run make init}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_USERS_DEFAULT_THEME: dark
      GF_SERVER_ROOT_URL: ${GRAFANA_ROOT_URL:-http://localhost:3001/}
      INFLUXDB_READ_PASSWORD: ${INFLUXDB_READ_PASSWORD:?Run make init}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./provisioning:/etc/grafana/provisioning:ro
      - ./projects:/var/lib/grafana/dashboards/projects:ro
    depends_on:
      influxdb:
        condition: service_healthy
    logging: *container-logging

volumes:
  grafana-data:
    name: ${GRAFANA_VOLUME:-graphana-skynet-dashboards_grafana-data}
  influxdb-data:
    name: ${INFLUXDB_VOLUME:-graphana-skynet-dashboards_influxdb-data}
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/docs/IMPORTING.md

````markdown
# Добавление дашбордов проекта

Дашборд — определение визуализаций, запросов и переменных. Он не содержит
хранилище метрик, пароли datasource, плагины, правила маршрутизации сети
и содержимое внешних файлов. Эти зависимости подключаются отдельно.

## 1. Подключите datasource

В новой Grafana откройте **Connections → Data sources → Add data source**.
Выберите тот же тип и язык запросов, которые использует исходный дашборд.
Укажите URL, credentials и остальные параметры, затем выполните **Save & test**.
UID можно посмотреть в настройках/URL страницы datasource или получить через API.

Встроенный источник уже подготовлен:

| Имя | UID | Тип | Язык | База |
| --- | --- | --- | --- | --- |
| InfluxDB-Telegraf | skynet-influxdb-telegraf | InfluxDB | InfluxQL | telegraf |

Совпадение отображаемого имени не гарантирует совпадения UID между инстансами.
Запросы PromQL, LogQL, Flux, InfluxQL и SQL не преобразуются простой заменой UID.
Импортёр сохраняет запросы; сопоставляйте только совместимые datasource.

Если источник должен управляться через Git, добавьте отдельный YAML в
`provisioning/datasources/`. Пример структуры для внешнего Prometheus:

```yaml
apiVersion: 1
datasources:
  - name: Project Metrics
    uid: project-metrics
    type: prometheus
    access: proxy
    url: $PROJECT_METRICS_URL
    isDefault: false
    editable: false
```

Это шаблон, не описание существующего источника. Задайте его реальный URL
и передайте переменную **в контейнер Grafana**. Наличие переменной только в `.env`
не добавляет её в environment контейнера автоматически. Например, добавьте
к сервису `grafana` в Compose:

```yaml
environment:
  PROJECT_METRICS_URL: ${PROJECT_METRICS_URL:?Set the reachable backend URL}
```

Секреты задавайте через `secureJsonData` с переменными окружения. Не храните
credentials в JSON дашборда или YAML в Git. Глобальный `.env` описывает платформу;
дополнительные переменные вводятся только при подключении нового backend,
а не при добавлении каждого дашборда.

URL должен быть доступен **из контейнера Grafana**. `localhost` внутри него —
сам контейнер. Для backend в другом Compose можно использовать общую Docker-сеть
и сетевое имя сервиса; подключение этой сети настраивается в обоих Compose.
Для backend на хосте используйте доступный адрес хоста или host-gateway alias,
который явно добавлен в Compose. Вместе с источником перенесите настройки
аутентификации, TLS, derived fields, ссылки и внешние сервисы, если они нужны.
Не сохраняйте старые внутренние имена контейнеров, не доступные из новой сети.

Применение YAML datasource:

```bash
docker compose up -d
docker compose restart grafana
```

## 2. Экспортируйте исходный дашборд

В исходной Grafana откройте дашборд и меню экспорта, выберите **Classic JSON**.
Для прямого переноса можно экспортировать обычный JSON с исходными UID datasource.
Экспорт для внешнего использования часто создаёт `__inputs` и ссылки вида
`${DS_METRICS}` — их потребуется сопоставить при импорте.

Скачанный JSON с Grafana.com также можно использовать. Сохраните лицензию
и сведения об авторе внешнего дашборда. Library panels, дополнительные panel
plugins, alert rules и recording rules требуют отдельного переноса/установки.
Если возможно, преобразуйте library panels в обычные панели перед экспортом.

Скрипт поддерживает Classic JSON и ответ API вида `{"dashboard": {...}, "meta": {...}}`.
V2/resource JSON не преобразуется: экспортируйте Classic или импортируйте V2
через поддерживаемый UI, затем экспортируйте подходящую модель.

## 3. Выберите способ импорта

### Через Grafana UI

1. Откройте **Dashboards → New → Import**, загрузите JSON или укажите ID/URL
   из каталога Grafana.com.
2. Выберите папку **Projects**, название и UID. Если создаёте копию, UID должен
   отличаться от исходного. Не подтверждайте перезапись чужого дашборда.
3. Сопоставьте предложенные datasource. Для экспорта с жёсткими UID форма может
   не предложить выбор — обновите datasource панелей и переменных самостоятельно
   либо используйте скрипт ниже.
4. Проверьте панели, переменные, annotations, повторяемые строки, links и queries.
5. Если дашборд должен храниться в Git, экспортируйте настроенный Classic JSON
   и добавьте его в `projects/`. Сохранение через UI само по себе файл не создаёт.

UID дашборда, импортированного в UI, можно затем сохранить в Git: при загрузке
provider будет обновлять именно этот дашборд и управлять им из файлов.
После перехода на provisioning редактируйте источник в Git; UI-сохранение
отключено текущим provider.

### Через Git и provisioning

Из корня репозитория выполните команду, подставив свой экспорт и UID источников:

```bash
python3 scripts/import_dashboard.py /tmp/dashboard.json \
  --uid project-overview \
  --title "Project Overview" \
  --datasource old-influx-uid=skynet-influxdb-telegraf \
  --output projects/project-overview.json
```

Для external export с datasource input `DS_METRICS`:

```bash
python3 scripts/import_dashboard.py /tmp/dashboard.json \
  --uid project-overview \
  --datasource DS_METRICS=skynet-influxdb-telegraf
```

Если источников несколько, повторите `--datasource` для каждого. Формат слева —
точное старое значение datasource (UID или legacy имя) либо имя из `__inputs`;
справа — UID источника в новой Grafana. В частности, два inputs одного типа
можно направить в разные источники. Их нельзя объединять только по типу плагина.
Для `${DS_NAME}`, объявленного в `templating.list`, сохраните саму переменную,
исправьте её regex при несовпадающем имени datasource и при необходимости
сопоставьте UID в `current.value`.

Если UID datasource одинаков в обоих инстансах, аргумент `--datasource` не нужен.
Если не задан `--uid`, сохраняется UID из экспорта, а при его отсутствии создаётся
новый. Если не задан `--output`, файл записывается в `projects/<uid>.json`.

Импортёр:

- устанавливает dashboard `id: null`, `version: 1`;
- сохраняет ID панелей, queries, layout и остальные настройки;
- заменяет datasource в панелях, targets, annotations и query variables;
- обновляет выбранный UID у datasource variables;
- раскрывает datasource `__inputs`; inputs других типов требует сначала
  разрешить через UI;
- проверяет уникальность UID/названий среди JSON в `projects/`, включая подпапки;
- не перезаписывает существующий файл без `--overwrite`;
- сохраняет только внутрь `projects/`.

Он не обращается к Grafana API и не проверяет существование datasource или
установку плагинов на сервере. Перед первым импортом проверьте UID в Grafana:
совпадение с существующим дашбордом приведёт к его обновлению provisioning.

После подготовки:

```bash
make check
git add projects/
git commit -m "Add project dashboard"
git push origin main
```

На сервере:

```bash
git pull --ff-only origin main
make check
docker compose up -d
```

При работающей Grafana JSON перечитываются каждые 30s. Для нового дашборда
не нужны новая строка в `.env`, отдельный provider или изменение Compose.

Краткий эквивалент команды: `make import-dashboard ARGS='/tmp/dashboard.json --uid project-overview'`.
Для путей/названий с пробелами удобнее вызывать Python напрямую с обычным shell quoting.

## 4. Обновляйте без изменения идентичности

```bash
python3 scripts/import_dashboard.py /tmp/updated-dashboard.json \
  --uid project-overview \
  --output projects/project-overview.json \
  --overwrite
make check
```

Сохраняйте UID для обновления того же дашборда. `--overwrite` разрешает замену
только указанного файла и не отключает проверку конфликтов с другими файлами.
Существующие файлы проверяются до записи. Повторяйте нужные datasource mappings,
если новый экспорт всё ещё содержит старые ссылки или `__inputs`.

`make check` проверяет JSON, уникальность идентификаторов и переменные datasource.
Валидатор допускает другие типы панелей и datasource; корректность их запросов
и наличие плагинов проверяются в самой Grafana. Ограничение репозитория —
Classic JSON с явными уникальными числовыми ID панелей.

## 5. Проверка в Grafana

- **Connections → Data sources → Save & test**: источник доступен.
- **Dashboards → Projects**: нужный дашборд появился.
- Выберите актуальный период, затем отдельный host и All, если эти переменные есть.
- **Inspect → Query**: нет старых UID, нераскрытых `${DS_*}` и ошибок запроса.
- Убедитесь, что название measurement/метрики, поля, теги и язык запросов
  соответствуют backend. Проверяйте их в Explore.
- Проверьте annotations, dashboard links, data links и внешние файлы отдельно.

Если JSON удалён, дашборд может остаться в базе: provider настроен с
`disableDeletion: true`. Если JSON изменён, но не обновился, проверьте mount
`projects` и `docker compose logs --tail=100 grafana`.

Источники: [импорт Grafana](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/import-dashboards/),
[file provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
````

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/docs/PANELS.md

````markdown
# Каталог панелей

Сгенерировано из поставляемых JSON. Для stat легенда отображается как имя значения; для timeseries — в таблице под графиком. `null` в thresholds обозначает базовую ступень.

## Server Resources Overview

| ID | Panel | Type | Unit | Thresholds |
| --- | --- | --- | --- | --- |
| 1 | CPU % | stat | percent | green: None, yellow: 80, red: 90 |
| 2 | RAM % | stat | percent | green: None, yellow: 80, red: 90 |
| 3 | Disk % by mount | stat | percent | green: None, yellow: 80, red: 90 |
| 4 | Load Average (1m) | stat | short | green: None |
| 5 | Uptime | stat | s | green: None |
| 6 | CPU total utilization | timeseries | percent | green: None, yellow: 80, red: 90 |
| 7 | CPU utilization by core | timeseries | percent | green: None, yellow: 80, red: 90 |
| 8 | CPU modes | timeseries | percent | green: None, yellow: 80, red: 90 |
| 9 | CPU I/O wait | timeseries | percent | green: None, yellow: 80, red: 90 |
| 10 | Memory capacity | timeseries | bytes | green: None |
| 11 | Memory utilization | timeseries | percent | green: None, yellow: 80, red: 90 |
| 12 | Swap capacity | timeseries | bytes | green: None |
| 13 | Swap utilization | timeseries | percent | green: None, yellow: 80, red: 90 |
| 14 | Disk capacity by mount | timeseries | bytes | green: None |
| 15 | Disk utilization by mount | timeseries | percent | green: None, yellow: 80, red: 90 |
| 16 | Inodes by mount | timeseries | short | green: None |
| 17 | Inode utilization by mount | timeseries | percent | green: None, yellow: 80, red: 90 |
| 18 | Disk I/O throughput | timeseries | Bps | green: None |
| 19 | Disk I/O accumulated time rate | timeseries | suffix:ms/s | green: None |
| 20 | Network traffic | timeseries | Bps | green: None |
| 21 | Network packets | timeseries | pps | green: None |
| 22 | Network errors | timeseries | suffix:errors/s | green: None, red: 1 |
| 23 | Network drops | timeseries | suffix:drops/s | green: None, red: 1 |
| 24 | Processes | timeseries | short | green: None |
| 25 | Blocked and zombie processes | timeseries | short | green: None, red: 1 |
| 26 | Load averages | timeseries | short | green: None |
| 27 | Logged-in users | timeseries | short | green: None |

### 1. CPU %

Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.

Target A; legend: `[[tag_host]] [[tag_cpu]] · busy`.

```sql
SELECT 100 - mean("usage_idle") AS "busy" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

### 2. RAM %

Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.

Target A; legend: `[[tag_host]] · used`.

```sql
SELECT mean("used_percent") AS "used" FROM "mem" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 3. Disk % by mount

Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.

Target A; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · used`.

```sql
SELECT mean("used_percent") AS "used" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

### 4. Load Average (1m)

Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.

Target A; legend: `[[tag_host]] · load1`.

```sql
SELECT mean("load1") AS "load1" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 5. Uptime

Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.

Target A; legend: `[[tag_host]] · uptime`.

```sql
SELECT last("uptime") AS "uptime" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 6. CPU total utilization

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_cpu]] · busy`.

```sql
SELECT 100 - mean("usage_idle") AS "busy" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

### 7. CPU utilization by core

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_cpu]] · busy`.

```sql
SELECT 100 - mean("usage_idle") AS "busy" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" != 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

### 8. CPU modes

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_cpu]] · user`.

```sql
SELECT mean("usage_user") AS "user" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_cpu]] · system`.

```sql
SELECT mean("usage_system") AS "system" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

Target C; legend: `[[tag_host]] [[tag_cpu]] · idle`.

```sql
SELECT mean("usage_idle") AS "idle" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

### 9. CPU I/O wait

Percentage of CPU time waiting for I/O; the generic 80/90 thresholds may need lower values for your workload.

Target A; legend: `[[tag_host]] [[tag_cpu]] · iowait`.

```sql
SELECT mean("usage_iowait") AS "iowait" FROM "cpu" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "cpu" = 'cpu-total' GROUP BY time($interval), "host", "cpu" fill(null)
```

### 10. Memory capacity

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · used`.

```sql
SELECT mean("used") AS "used" FROM "mem" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target B; legend: `[[tag_host]] · available`.

```sql
SELECT mean("available") AS "available" FROM "mem" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target C; legend: `[[tag_host]] · total`.

```sql
SELECT mean("total") AS "total" FROM "mem" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 11. Memory utilization

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · used`.

```sql
SELECT mean("used_percent") AS "used" FROM "mem" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 12. Swap capacity

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · used`.

```sql
SELECT mean("used") AS "used" FROM "swap" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target B; legend: `[[tag_host]] · free`.

```sql
SELECT mean("free") AS "free" FROM "swap" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target C; legend: `[[tag_host]] · total`.

```sql
SELECT mean("total") AS "total" FROM "swap" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 13. Swap utilization

Hosts without swap may report zero or no series. Missing data is not filled with zero.

Target A; legend: `[[tag_host]] · used`.

```sql
SELECT mean("used_percent") AS "used" FROM "swap" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 14. Disk capacity by mount

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · used`.

```sql
SELECT mean("used") AS "used" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · free`.

```sql
SELECT mean("free") AS "free" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

Target C; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · total`.

```sql
SELECT mean("total") AS "total" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

### 15. Disk utilization by mount

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · used`.

```sql
SELECT mean("used_percent") AS "used" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

### 16. Inodes by mount

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · inodes_used`.

```sql
SELECT mean("inodes_used") AS "inodes_used" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · inodes_free`.

```sql
SELECT mean("inodes_free") AS "inodes_free" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ GROUP BY time($interval), "host", "device", "path" fill(null)
```

### 17. Inode utilization by mount

Used / (used + free). Filesystems reporting no inodes are excluded to avoid division by zero.

Target A; legend: `[[tag_host]] [[tag_device]] [[tag_path]] · used`.

```sql
SELECT 100 * mean("inodes_used") / (mean("inodes_used") + mean("inodes_free")) AS "used" FROM "disk" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/ AND ("inodes_used" > 0 OR "inodes_free" > 0) GROUP BY time($interval), "host", "device", "path" fill(null)
```

### 18. Disk I/O throughput

Non-negative rate of cumulative bytes, grouped by host and device. Counter resets create gaps; the first bucket needs a preceding sample.

Target A; legend: `[[tag_host]] [[tag_name]] · read`.

```sql
SELECT non_negative_derivative(last("read_bytes"), 1s) AS "read" FROM "diskio" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "name" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), "host", "name" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_name]] · write`.

```sql
SELECT non_negative_derivative(last("write_bytes"), 1s) AS "write" FROM "diskio" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "name" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), "host", "name" fill(null)
```

### 19. Disk I/O accumulated time rate

Rate of cumulative read_time/write_time (milliseconds per second). This is NOT latency per operation or disk utilization; concurrent requests may exceed 1000 ms/s. Operation counters are not in the supplied schema.

Target A; legend: `[[tag_host]] [[tag_name]] · read`.

```sql
SELECT non_negative_derivative(last("read_time"), 1s) AS "read" FROM "diskio" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "name" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), "host", "name" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_name]] · write`.

```sql
SELECT non_negative_derivative(last("write_time"), 1s) AS "write" FROM "diskio" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "name" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), "host", "name" fill(null)
```

### 20. Network traffic

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_interface]] · receive`.

```sql
SELECT non_negative_derivative(last("bytes_recv"), 1s) AS "receive" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_interface]] · send`.

```sql
SELECT non_negative_derivative(last("bytes_sent"), 1s) AS "send" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

### 21. Network packets

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_interface]] · receive`.

```sql
SELECT non_negative_derivative(last("packets_recv"), 1s) AS "receive" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_interface]] · send`.

```sql
SELECT non_negative_derivative(last("packets_sent"), 1s) AS "send" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

### 22. Network errors

Counter rate; red at >= 1 error/s. Smaller positive rates are still worth investigating.

Target A; legend: `[[tag_host]] [[tag_interface]] · in`.

```sql
SELECT non_negative_derivative(last("err_in"), 1s) AS "in" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_interface]] · out`.

```sql
SELECT non_negative_derivative(last("err_out"), 1s) AS "out" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

### 23. Network drops

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] [[tag_interface]] · in`.

```sql
SELECT non_negative_derivative(last("drop_in"), 1s) AS "in" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

Target B; legend: `[[tag_host]] [[tag_interface]] · out`.

```sql
SELECT non_negative_derivative(last("drop_out"), 1s) AS "out" FROM "net" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ AND "interface" =~ /^${interface:regex}$/ GROUP BY time($interval), "host", "interface" fill(null)
```

### 24. Processes

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · total`.

```sql
SELECT mean("total") AS "total" FROM "processes" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target B; legend: `[[tag_host]] · running`.

```sql
SELECT mean("running") AS "running" FROM "processes" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target C; legend: `[[tag_host]] · sleeping`.

```sql
SELECT mean("sleeping") AS "sleeping" FROM "processes" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 25. Blocked and zombie processes

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · blocked`.

```sql
SELECT mean("blocked") AS "blocked" FROM "processes" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target B; legend: `[[tag_host]] · zombies`.

```sql
SELECT mean("zombies") AS "zombies" FROM "processes" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 26. Load averages

Runnable/uninterruptible tasks, not a percentage. Compare with logical CPU count; no universal absolute threshold is applied.

Target A; legend: `[[tag_host]] · load1`.

```sql
SELECT mean("load1") AS "load1" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target B; legend: `[[tag_host]] · load5`.

```sql
SELECT mean("load5") AS "load5" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

Target C; legend: `[[tag_host]] · load15`.

```sql
SELECT mean("load15") AS "load15" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```

### 27. Logged-in users

Запрос и представление из JSON.

Target A; legend: `[[tag_host]] · users`.

```sql
SELECT mean("n_users") AS "users" FROM "system" WHERE $timeFilter AND "host" =~ /^${host:regex}$/ GROUP BY time($interval), "host" fill(null)
```
````

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/docs/VALIDATION.md

````markdown
# Проверки конфигурации

Для локальной проверки требуются Python 3.11+ и Docker Compose CLI:

```bash
make test
make check
```

`make test` проверяет импорт Classic/API JSON, вложенные панели, замену нескольких
источников данных в панелях/targets/annotations/variables, сохранение запросов
и ID панелей, обработку `__inputs`, конфликты UID/названий, защиту от случайной
перезаписи и записи за пределами `projects/`.

Семантика встроенного серверного дашборда проверяется отдельным тестом:
схема measurements/fields/tags, группировки, interval, rates и Telegraf TOML.
Эти ограничения не применяются к другим импортированным дашбордам.

`make check` проверяет произвольное количество JSON в `projects/` и подпапках,
а затем выполняет `docker compose config --quiet` с текущим `.env`.
Он не ограничивает тип datasource, язык запросов или набор panel plugins.

## Результат подготовки

- 11 автоматических тестов прошли.
- Универсальная проверка JSON и Telegraf TOML прошла.
- Compose нормализуется: Grafana, InfluxDB и Telegraf, два volumes.
- Запуск импортёра как CLI проверен на временном JSON, включая подпапку
  и отказ от перезаписи без `--overwrite`.
- Текущий `.env` содержит только параметры платформы, исключён из Git,
  права доступа 0600. Реальные секреты не включены в архивы или документацию.

## Проверка на целевом Linux

```bash
make check-runtime
make up
docker compose ps
docker compose logs --tail=100 grafana influxdb telegraf
```

При подготовке локальный Docker daemon недоступен, поэтому контейнерные
проверки, реальное выполнение запросов и отображение в Grafana не выполнялись.
Офлайн-проверка не подтверждает доступность datasource, установку panel plugins,
корректность всех языков запросов, работоспособность data links и сети.

После запуска выполните проверки из [IMPORTING.md](IMPORTING.md): Save & test,
Explore, Inspect → Query, переменные и ссылки. Ни `make check`, ни импортёр
не обращаются к Grafana API и не проверяют конфликты с дашбордами вне Git.
````

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/licenses/provenance.json

```json
{
  "source_repository": "https://github.com/mrsadman99/parser_avito",
  "source_commit": "98a73dca18f8402dbdf1b56a80918be033577d3f",
  "source_files_sha256": {
    "docker-compose.monitoring.yml": "bd7e85b51a862927cb9e5d5562492572e0d50c817ec754b919385e8a320083c6"
  },
  "license_status": "No license file found in inspected source checkout",
  "scope": "Historical provenance of the initial Docker Compose configuration; not an active integration."
}
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/monitoring/influxdb/retention.iql

```sql
CREATE RETENTION POLICY "telegraf" ON "telegraf" DURATION 30d REPLICATION 1 DEFAULT
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/monitoring/telegraf/telegraf.conf

```toml
[agent]
  interval = "10s"
  round_interval = true
  flush_interval = "10s"
  metric_batch_size = 1000
  metric_buffer_limit = 10000
  hostname = "${TELEGRAF_HOST}"
  omit_hostname = false

[[outputs.influxdb]]
  urls = ["${INFLUXDB_URL}"]
  database = "telegraf"
  retention_policy = "telegraf"
  skip_database_creation = true
  username = "telegraf"
  password = "${INFLUXDB_WRITE_PASSWORD}"
  timeout = "5s"

[[inputs.cpu]]
  percpu = true
  totalcpu = true
  collect_cpu_time = false
  report_active = false

[[inputs.mem]]
[[inputs.swap]]

[[inputs.disk]]
  ignore_fs = ["tmpfs", "devtmpfs", "devfs", "overlay", "aufs", "squashfs", "nsfs", "proc", "sysfs", "cgroup", "cgroup2"]

[[inputs.diskio]]
[[inputs.net]]
[[inputs.system]]
[[inputs.processes]]
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/projects/server-resources-overview.json

```json
{
  "id": null,
  "uid": "skynet-server-resources",
  "title": "Server Resources Overview",
  "description": "Linux host resources from Telegraf (10s) and InfluxDB 1.x / InfluxQL. Counters use non-negative rates; missing values stay null.",
  "tags": [
    "skynet",
    "server",
    "telegraf",
    "influxdb"
  ],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "style": "dark",
  "refresh": "30s",
  "time": {
    "from": "now-30m",
    "to": "now"
  },
  "timepicker": {
    "refresh_intervals": [
      "10s",
      "30s",
      "1m",
      "5m"
    ]
  },
  "annotations": {
    "list": []
  },
  "links": [],
  "templating": {
    "list": [
      {
        "name": "DS_INFLUXDB",
        "label": "Datasource",
        "type": "datasource",
        "query": "influxdb",
        "regex": "/^InfluxDB-Telegraf$/",
        "refresh": 1,
        "current": {
          "text": "InfluxDB-Telegraf",
          "value": "skynet-influxdb-telegraf"
        },
        "options": []
      },
      {
        "name": "host",
        "label": "Host",
        "type": "query",
        "datasource": {
          "type": "influxdb",
          "uid": "${DS_INFLUXDB}"
        },
        "query": "SHOW TAG VALUES FROM \"cpu\" WITH KEY = \"host\"",
        "definition": "SHOW TAG VALUES FROM \"cpu\" WITH KEY = \"host\"",
        "refresh": 1,
        "sort": 1,
        "multi": true,
        "includeAll": true,
        "allValue": ".*",
        "current": {
          "text": [
            "All"
          ],
          "value": [
            "$__all"
          ]
        },
        "options": []
      },
      {
        "name": "interval",
        "label": "Interval",
        "type": "interval",
        "query": "10s,30s,1m,5m,15m,1h",
        "auto": true,
        "auto_min": "10s",
        "auto_count": 100,
        "current": {
          "text": "10s",
          "value": "10s"
        },
        "options": [
          {
            "text": "10s",
            "value": "10s",
            "selected": true
          },
          {
            "text": "30s",
            "value": "30s",
            "selected": false
          },
          {
            "text": "1m",
            "value": "1m",
            "selected": false
          },
          {
            "text": "5m",
            "value": "5m",
            "selected": false
          },
          {
            "text": "15m",
            "value": "15m",
            "selected": false
          },
          {
            "text": "1h",
            "value": "1h",
            "selected": false
          }
        ]
      },
      {
        "name": "device",
        "label": "Disk device",
        "type": "query",
        "datasource": {
          "type": "influxdb",
          "uid": "${DS_INFLUXDB}"
        },
        "query": "SHOW TAG VALUES FROM \"disk\" WITH KEY = \"device\" WHERE \"host\" =~ /^${host:regex}$/",
        "definition": "SHOW TAG VALUES FROM \"disk\" WITH KEY = \"device\" WHERE \"host\" =~ /^${host:regex}$/",
        "refresh": 1,
        "sort": 1,
        "multi": true,
        "includeAll": true,
        "allValue": ".*",
        "current": {
          "text": [
            "All"
          ],
          "value": [
            "$__all"
          ]
        },
        "options": []
      },
      {
        "name": "path",
        "label": "Mount path",
        "type": "query",
        "datasource": {
          "type": "influxdb",
          "uid": "${DS_INFLUXDB}"
        },
        "query": "SHOW TAG VALUES FROM \"disk\" WITH KEY = \"path\" WHERE \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/",
        "definition": "SHOW TAG VALUES FROM \"disk\" WITH KEY = \"path\" WHERE \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/",
        "refresh": 1,
        "sort": 1,
        "multi": true,
        "includeAll": true,
        "allValue": ".*",
        "current": {
          "text": [
            "All"
          ],
          "value": [
            "$__all"
          ]
        },
        "options": []
      },
      {
        "name": "diskio_device",
        "label": "I/O device",
        "type": "query",
        "datasource": {
          "type": "influxdb",
          "uid": "${DS_INFLUXDB}"
        },
        "query": "SHOW TAG VALUES FROM \"diskio\" WITH KEY = \"name\" WHERE \"host\" =~ /^${host:regex}$/",
        "definition": "SHOW TAG VALUES FROM \"diskio\" WITH KEY = \"name\" WHERE \"host\" =~ /^${host:regex}$/",
        "refresh": 1,
        "sort": 1,
        "multi": true,
        "includeAll": true,
        "allValue": ".*",
        "current": {
          "text": [
            "All"
          ],
          "value": [
            "$__all"
          ]
        },
        "options": []
      },
      {
        "name": "interface",
        "label": "Network interface",
        "type": "query",
        "datasource": {
          "type": "influxdb",
          "uid": "${DS_INFLUXDB}"
        },
        "query": "SHOW TAG VALUES FROM \"net\" WITH KEY = \"interface\" WHERE \"host\" =~ /^${host:regex}$/",
        "definition": "SHOW TAG VALUES FROM \"net\" WITH KEY = \"interface\" WHERE \"host\" =~ /^${host:regex}$/",
        "refresh": 1,
        "sort": 1,
        "multi": true,
        "includeAll": true,
        "allValue": ".*",
        "current": {
          "text": [
            "All"
          ],
          "value": [
            "$__all"
          ]
        },
        "options": []
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "type": "stat",
      "title": "CPU %",
      "description": "Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 0,
        "w": 5,
        "h": 5
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "thresholds"
          },
          "mappings": [],
          "max": 100
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
        "orientation": "auto",
        "justifyMode": "auto",
        "wideLayout": true
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT 100 - mean(\"usage_idle\") AS \"busy\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · busy"
        }
      ]
    },
    {
      "id": 2,
      "type": "stat",
      "title": "RAM %",
      "description": "Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 5,
        "y": 0,
        "w": 5,
        "h": 5
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "thresholds"
          },
          "mappings": [],
          "max": 100
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
        "orientation": "auto",
        "justifyMode": "auto",
        "wideLayout": true
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used_percent\") AS \"used\" FROM \"mem\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · used"
        }
      ]
    },
    {
      "id": 3,
      "type": "stat",
      "title": "Disk % by mount",
      "description": "Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 10,
        "y": 0,
        "w": 5,
        "h": 5
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "thresholds"
          },
          "mappings": [],
          "max": 100
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
        "orientation": "auto",
        "justifyMode": "auto",
        "wideLayout": true
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used_percent\") AS \"used\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · used"
        }
      ]
    },
    {
      "id": 4,
      "type": "stat",
      "title": "Load Average (1m)",
      "description": "Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 15,
        "y": 0,
        "w": 5,
        "h": 5
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "thresholds"
          },
          "mappings": []
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
        "orientation": "auto",
        "justifyMode": "auto",
        "wideLayout": true
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"load1\") AS \"load1\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · load1"
        }
      ]
    },
    {
      "id": 5,
      "type": "stat",
      "title": "Uptime",
      "description": "Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 20,
        "y": 0,
        "w": 4,
        "h": 5
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "thresholds"
          },
          "mappings": []
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ],
          "fields": "",
          "values": false
        },
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
        "orientation": "auto",
        "justifyMode": "auto",
        "wideLayout": true
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT last(\"uptime\") AS \"uptime\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · uptime"
        }
      ]
    },
    {
      "id": 6,
      "type": "timeseries",
      "title": "CPU total utilization",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 5,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT 100 - mean(\"usage_idle\") AS \"busy\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · busy"
        }
      ]
    },
    {
      "id": 7,
      "type": "timeseries",
      "title": "CPU utilization by core",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 5,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT 100 - mean(\"usage_idle\") AS \"busy\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" != 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · busy"
        }
      ]
    },
    {
      "id": 8,
      "type": "timeseries",
      "title": "CPU modes",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 13,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"usage_user\") AS \"user\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · user"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"usage_system\") AS \"system\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · system"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"usage_idle\") AS \"idle\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · idle"
        }
      ]
    },
    {
      "id": 9,
      "type": "timeseries",
      "title": "CPU I/O wait",
      "description": "Percentage of CPU time waiting for I/O; the generic 80/90 thresholds may need lower values for your workload.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 13,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"usage_iowait\") AS \"iowait\" FROM \"cpu\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"cpu\" = 'cpu-total' GROUP BY time($interval), \"host\", \"cpu\" fill(null)",
          "alias": "[[tag_host]] [[tag_cpu]] · iowait"
        }
      ]
    },
    {
      "id": 10,
      "type": "timeseries",
      "title": "Memory capacity",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 21,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "bytes",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used\") AS \"used\" FROM \"mem\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · used"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"available\") AS \"available\" FROM \"mem\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · available"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"total\") AS \"total\" FROM \"mem\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · total"
        }
      ]
    },
    {
      "id": 11,
      "type": "timeseries",
      "title": "Memory utilization",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 21,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used_percent\") AS \"used\" FROM \"mem\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · used"
        }
      ]
    },
    {
      "id": 12,
      "type": "timeseries",
      "title": "Swap capacity",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 29,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "bytes",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used\") AS \"used\" FROM \"swap\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · used"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"free\") AS \"free\" FROM \"swap\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · free"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"total\") AS \"total\" FROM \"swap\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · total"
        }
      ]
    },
    {
      "id": 13,
      "type": "timeseries",
      "title": "Swap utilization",
      "description": "Hosts without swap may report zero or no series. Missing data is not filled with zero.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 29,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used_percent\") AS \"used\" FROM \"swap\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · used"
        }
      ]
    },
    {
      "id": 14,
      "type": "timeseries",
      "title": "Disk capacity by mount",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 37,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "bytes",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used\") AS \"used\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · used"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"free\") AS \"free\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · free"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"total\") AS \"total\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · total"
        }
      ]
    },
    {
      "id": 15,
      "type": "timeseries",
      "title": "Disk utilization by mount",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 37,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"used_percent\") AS \"used\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · used"
        }
      ]
    },
    {
      "id": 16,
      "type": "timeseries",
      "title": "Inodes by mount",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 45,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"inodes_used\") AS \"inodes_used\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · inodes_used"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"inodes_free\") AS \"inodes_free\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · inodes_free"
        }
      ]
    },
    {
      "id": 17,
      "type": "timeseries",
      "title": "Inode utilization by mount",
      "description": "Used / (used + free). Filesystems reporting no inodes are excluded to avoid division by zero.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 45,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "yellow",
                "value": 80
              },
              {
                "color": "red",
                "value": 90
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "max": 100,
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT 100 * mean(\"inodes_used\") / (mean(\"inodes_used\") + mean(\"inodes_free\")) AS \"used\" FROM \"disk\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"device\" =~ /^${device:regex}$/ AND \"path\" =~ /^${path:regex}$/ AND (\"inodes_used\" > 0 OR \"inodes_free\" > 0) GROUP BY time($interval), \"host\", \"device\", \"path\" fill(null)",
          "alias": "[[tag_host]] [[tag_device]] [[tag_path]] · used"
        }
      ]
    },
    {
      "id": 18,
      "type": "timeseries",
      "title": "Disk I/O throughput",
      "description": "Non-negative rate of cumulative bytes, grouped by host and device. Counter resets create gaps; the first bucket needs a preceding sample.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 53,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "Bps",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"read_bytes\"), 1s) AS \"read\" FROM \"diskio\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"name\" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), \"host\", \"name\" fill(null)",
          "alias": "[[tag_host]] [[tag_name]] · read"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"write_bytes\"), 1s) AS \"write\" FROM \"diskio\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"name\" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), \"host\", \"name\" fill(null)",
          "alias": "[[tag_host]] [[tag_name]] · write"
        }
      ]
    },
    {
      "id": 19,
      "type": "timeseries",
      "title": "Disk I/O accumulated time rate",
      "description": "Rate of cumulative read_time/write_time (milliseconds per second). This is NOT latency per operation or disk utilization; concurrent requests may exceed 1000 ms/s. Operation counters are not in the supplied schema.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 53,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "suffix:ms/s",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"read_time\"), 1s) AS \"read\" FROM \"diskio\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"name\" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), \"host\", \"name\" fill(null)",
          "alias": "[[tag_host]] [[tag_name]] · read"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"write_time\"), 1s) AS \"write\" FROM \"diskio\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"name\" =~ /^${diskio_device:regex}$/ GROUP BY time($interval), \"host\", \"name\" fill(null)",
          "alias": "[[tag_host]] [[tag_name]] · write"
        }
      ]
    },
    {
      "id": 20,
      "type": "timeseries",
      "title": "Network traffic",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 61,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "Bps",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"bytes_recv\"), 1s) AS \"receive\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · receive"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"bytes_sent\"), 1s) AS \"send\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · send"
        }
      ]
    },
    {
      "id": 21,
      "type": "timeseries",
      "title": "Network packets",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 61,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "pps",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"packets_recv\"), 1s) AS \"receive\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · receive"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"packets_sent\"), 1s) AS \"send\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · send"
        }
      ]
    },
    {
      "id": 22,
      "type": "timeseries",
      "title": "Network errors",
      "description": "Counter rate; red at >= 1 error/s. Smaller positive rates are still worth investigating.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 69,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "suffix:errors/s",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "red",
                "value": 1
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"err_in\"), 1s) AS \"in\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · in"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"err_out\"), 1s) AS \"out\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · out"
        }
      ]
    },
    {
      "id": 23,
      "type": "timeseries",
      "title": "Network drops",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 69,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "suffix:drops/s",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "red",
                "value": 1
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"drop_in\"), 1s) AS \"in\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · in"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT non_negative_derivative(last(\"drop_out\"), 1s) AS \"out\" FROM \"net\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ AND \"interface\" =~ /^${interface:regex}$/ GROUP BY time($interval), \"host\", \"interface\" fill(null)",
          "alias": "[[tag_host]] [[tag_interface]] · out"
        }
      ]
    },
    {
      "id": 24,
      "type": "timeseries",
      "title": "Processes",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 77,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"total\") AS \"total\" FROM \"processes\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · total"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"running\") AS \"running\" FROM \"processes\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · running"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"sleeping\") AS \"sleeping\" FROM \"processes\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · sleeping"
        }
      ]
    },
    {
      "id": 25,
      "type": "timeseries",
      "title": "Blocked and zombie processes",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 77,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "red",
                "value": 1
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "dashed"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"blocked\") AS \"blocked\" FROM \"processes\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · blocked"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"zombies\") AS \"zombies\" FROM \"processes\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · zombies"
        }
      ]
    },
    {
      "id": 26,
      "type": "timeseries",
      "title": "Load averages",
      "description": "Runnable/uninterruptible tasks, not a percentage. Compare with logical CPU count; no universal absolute threshold is applied.",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 0,
        "y": 85,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"load1\") AS \"load1\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · load1"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"load5\") AS \"load5\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · load5"
        },
        {
          "refId": "C",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"load15\") AS \"load15\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · load15"
        }
      ]
    },
    {
      "id": 27,
      "type": "timeseries",
      "title": "Logged-in users",
      "description": "",
      "datasource": {
        "type": "influxdb",
        "uid": "${DS_INFLUXDB}"
      },
      "gridPos": {
        "x": 12,
        "y": 85,
        "w": 12,
        "h": 8
      },
      "interval": "10s",
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "decimals": 1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              }
            ]
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": 10,
            "spanNulls": false,
            "showPoints": "never",
            "stacking": {
              "mode": "none",
              "group": "A"
            },
            "thresholdsStyle": {
              "mode": "off"
            }
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "table",
          "placement": "bottom",
          "showLegend": true,
          "calcs": [
            "lastNotNull",
            "max"
          ]
        },
        "tooltip": {
          "mode": "multi",
          "sort": "desc"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "influxdb",
            "uid": "${DS_INFLUXDB}"
          },
          "rawQuery": true,
          "resultFormat": "time_series",
          "query": "SELECT mean(\"n_users\") AS \"users\" FROM \"system\" WHERE $timeFilter AND \"host\" =~ /^${host:regex}$/ GROUP BY time($interval), \"host\" fill(null)",
          "alias": "[[tag_host]] · users"
        }
      ]
    }
  ]
}
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/provisioning/dashboards/default.yaml

```yaml
apiVersion: 1
providers:
  - name: skynet-projects
    orgId: 1
    folder: Projects
    type: file
    disableDeletion: true
    updateIntervalSeconds: 30
    allowUiUpdates: false
    options:
      path: /var/lib/grafana/dashboards/projects
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/provisioning/datasources/datasource.yaml

```yaml
apiVersion: 1
datasources:
  - name: InfluxDB-Telegraf
    uid: skynet-influxdb-telegraf
    type: influxdb
    access: proxy
    url: http://influxdb:8086
    user: grafana
    database: telegraf
    isDefault: true
    editable: false
    jsonData:
      version: InfluxQL
      dbName: telegraf
      httpMode: POST
      timeInterval: 10s
    secureJsonData:
      password: $INFLUXDB_READ_PASSWORD
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/scripts/build_dashboard.py

```python
#!/usr/bin/env python3
"""Build the server dashboard using only the documented Telegraf fields."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {"type": "influxdb", "uid": "${DS_INFLUXDB}"}
HOST = '"host" =~ /^${host:regex}$/'
DISK = '"device" =~ /^${device:regex}$/ AND "path" =~ /^${path:regex}$/'
IO = '"name" =~ /^${diskio_device:regex}$/'
NET = '"interface" =~ /^${interface:regex}$/'
ALL = {"text": ["All"], "value": ["$__all"]}


def variable(name, label, measurement, tag, condition=None):
    query = f'SHOW TAG VALUES FROM "{measurement}"'
    query += f' WITH KEY = "{tag}"'
    if condition:
        query += f" WHERE {condition}"
    return {"name": name, "label": label, "type": "query", "datasource": DS,
            "query": query, "definition": query, "refresh": 1, "sort": 1,
            "multi": True, "includeAll": True, "allValue": ".*",
            "current": ALL, "options": []}


def query(measurement, expression, tags=(), condition=None):
    group = ', '.join(['time($interval)', '"host"'] + [f'"{t}"' for t in tags])
    where = HOST + (f" AND {condition}" if condition else "")
    return (f'SELECT {expression} FROM "{measurement}" WHERE $timeFilter AND {where} '
            f'GROUP BY {group} fill(null)')


def mean(field):
    return f'mean("{field}")'


def rate(field):
    return f'non_negative_derivative(last("{field}"), 1s)'


panels = []


def panel(title, measurement, expressions, unit, *, tags=(), condition=None,
          percent=False, critical=False, stat=False, description="", pos=None):
    targets = []
    alias_tags = ' '.join(f'[[tag_{tag}]]' for tag in ('host', *tags))
    for i, (name, expression) in enumerate(expressions):
        targets.append({"refId": chr(65 + i), "datasource": DS,
                        "rawQuery": True, "resultFormat": "time_series",
                        "query": query(measurement, f'{expression} AS "{name}"', tags, condition),
                        "alias": f"{alias_tags} · {name}"})
    steps = [{"color": "green", "value": None}]
    if percent:
        steps += [{"color": "yellow", "value": 80}, {"color": "red", "value": 90}]
    elif critical:
        steps += [{"color": "red", "value": 1}]
    defaults = {"unit": unit, "min": 0, "decimals": 1,
                "thresholds": {"mode": "absolute", "steps": steps},
                "color": {"mode": "thresholds" if stat else "palette-classic"},
                "mappings": []}
    if percent:
        defaults["max"] = 100
    if stat:
        options = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                   "colorMode": "value", "graphMode": "none", "textMode": "auto",
                   "orientation": "auto", "justifyMode": "auto", "wideLayout": True}
    else:
        defaults["custom"] = {"drawStyle": "line", "lineInterpolation": "linear",
                              "lineWidth": 1, "fillOpacity": 10, "spanNulls": False,
                              "showPoints": "never", "stacking": {"mode": "none", "group": "A"},
                              "thresholdsStyle": {"mode": "dashed" if percent or critical else "off"}}
        options = {"legend": {"displayMode": "table", "placement": "bottom",
                              "showLegend": True, "calcs": ["lastNotNull", "max"]},
                   "tooltip": {"mode": "multi", "sort": "desc"}}
    if pos is None:
        index = len(panels) - 5
        pos = {"x": (index % 2) * 12, "y": 5 + (index // 2) * 8, "w": 12, "h": 8}
    panels.append({"id": len(panels) + 1, "type": "stat" if stat else "timeseries",
                   "title": title, "description": description,
                   "datasource": DS, "gridPos": pos, "interval": "10s",
                   "fieldConfig": {"defaults": defaults, "overrides": []},
                   "options": options, "targets": targets})


CPU = '"cpu" = \'cpu-total\''
BUSY = '100 - mean("usage_idle")'
for title, measurement, expressions, unit, tags, condition, is_pct, x, w in [
    ("CPU %", "cpu", [("busy", BUSY)], "percent", ("cpu",), CPU, True, 0, 5),
    ("RAM %", "mem", [("used", mean("used_percent"))], "percent", (), None, True, 5, 5),
    ("Disk % by mount", "disk", [("used", mean("used_percent"))], "percent", ("device", "path"), DISK, True, 10, 5),
    ("Load Average (1m)", "system", [("load1", mean("load1"))], "short", (), None, False, 15, 5),
    ("Uptime", "system", [("uptime", 'last("uptime")')], "s", (), None, False, 20, 4),
]:
    panel(title, measurement, expressions, unit, tags=tags, condition=condition,
          percent=is_pct, stat=True, pos={"x": x, "y": 0, "w": w, "h": 5},
          description="Last non-null bucket in the selected time range, separately for each series. Check time range and collector freshness if the host stops reporting.")

panel("CPU total utilization", "cpu", [("busy", BUSY)], "percent", tags=("cpu",), condition=CPU, percent=True)
panel("CPU utilization by core", "cpu", [("busy", BUSY)], "percent", tags=("cpu",), condition='"cpu" != \'cpu-total\'', percent=True)
panel("CPU modes", "cpu", [(f, mean("usage_" + f)) for f in ("user", "system", "idle")], "percent", tags=("cpu",), condition=CPU, percent=True)
panel("CPU I/O wait", "cpu", [("iowait", mean("usage_iowait"))], "percent", tags=("cpu",), condition=CPU, percent=True,
      description="Percentage of CPU time waiting for I/O; the generic 80/90 thresholds may need lower values for your workload.")
panel("Memory capacity", "mem", [(f, mean(f)) for f in ("used", "available", "total")], "bytes")
panel("Memory utilization", "mem", [("used", mean("used_percent"))], "percent", percent=True)
panel("Swap capacity", "swap", [(f, mean(f)) for f in ("used", "free", "total")], "bytes")
panel("Swap utilization", "swap", [("used", mean("used_percent"))], "percent", percent=True,
      description="Hosts without swap may report zero or no series. Missing data is not filled with zero.")
panel("Disk capacity by mount", "disk", [(f, mean(f)) for f in ("used", "free", "total")], "bytes", tags=("device", "path"), condition=DISK)
panel("Disk utilization by mount", "disk", [("used", mean("used_percent"))], "percent", tags=("device", "path"), condition=DISK, percent=True)
panel("Inodes by mount", "disk", [(f, mean(f)) for f in ("inodes_used", "inodes_free")], "short", tags=("device", "path"), condition=DISK)
panel("Inode utilization by mount", "disk", [("used", '100 * mean("inodes_used") / (mean("inodes_used") + mean("inodes_free"))')], "percent", tags=("device", "path"), condition=DISK + ' AND ("inodes_used" > 0 OR "inodes_free" > 0)', percent=True,
      description="Used / (used + free). Filesystems reporting no inodes are excluded to avoid division by zero.")
panel("Disk I/O throughput", "diskio", [(f, rate(f + "_bytes")) for f in ("read", "write")], "Bps", tags=("name",), condition=IO,
      description="Non-negative rate of cumulative bytes, grouped by host and device. Counter resets create gaps; the first bucket needs a preceding sample.")
panel("Disk I/O accumulated time rate", "diskio", [(f, rate(f + "_time")) for f in ("read", "write")], "suffix:ms/s", tags=("name",), condition=IO,
      description="Rate of cumulative read_time/write_time (milliseconds per second). This is NOT latency per operation or disk utilization; concurrent requests may exceed 1000 ms/s. Operation counters are not in the supplied schema.")
panel("Network traffic", "net", [("receive", rate("bytes_recv")), ("send", rate("bytes_sent"))], "Bps", tags=("interface",), condition=NET)
panel("Network packets", "net", [("receive", rate("packets_recv")), ("send", rate("packets_sent"))], "pps", tags=("interface",), condition=NET)
panel("Network errors", "net", [("in", rate("err_in")), ("out", rate("err_out"))], "suffix:errors/s", tags=("interface",), condition=NET, critical=True,
      description="Counter rate; red at >= 1 error/s. Smaller positive rates are still worth investigating.")
panel("Network drops", "net", [("in", rate("drop_in")), ("out", rate("drop_out"))], "suffix:drops/s", tags=("interface",), condition=NET, critical=True)
panel("Processes", "processes", [(f, mean(f)) for f in ("total", "running", "sleeping")], "short")
panel("Blocked and zombie processes", "processes", [(f, mean(f)) for f in ("blocked", "zombies")], "short", critical=True)
panel("Load averages", "system", [(f, mean(f)) for f in ("load1", "load5", "load15")], "short",
      description="Runnable/uninterruptible tasks, not a percentage. Compare with logical CPU count; no universal absolute threshold is applied.")
panel("Logged-in users", "system", [("users", mean("n_users"))], "short")

dashboard = {
    "id": None, "uid": "skynet-server-resources", "title": "Server Resources Overview",
    "description": "Linux host resources from Telegraf (10s) and InfluxDB 1.x / InfluxQL. Counters use non-negative rates; missing values stay null.",
    "tags": ["skynet", "server", "telegraf", "influxdb"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "editable": False, "style": "dark",
    "refresh": "30s", "time": {"from": "now-30m", "to": "now"},
    "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
    "annotations": {"list": []}, "links": [],
    "templating": {"list": [
        {"name": "DS_INFLUXDB", "label": "Datasource", "type": "datasource",
         "query": "influxdb", "regex": "/^InfluxDB-Telegraf$/", "refresh": 1,
         "current": {"text": "InfluxDB-Telegraf", "value": "skynet-influxdb-telegraf"}, "options": []},
        variable("host", "Host", "cpu", "host"),
        {"name": "interval", "label": "Interval", "type": "interval",
         "query": "10s,30s,1m,5m,15m,1h", "auto": True, "auto_min": "10s", "auto_count": 100,
         "current": {"text": "10s", "value": "10s"},
         "options": [{"text": v, "value": v, "selected": v == "10s"} for v in ("10s", "30s", "1m", "5m", "15m", "1h")]},
        variable("device", "Disk device", "disk", "device", HOST),
        variable("path", "Mount path", "disk", "path", HOST + ' AND "device" =~ /^${device:regex}$/'),
        variable("diskio_device", "I/O device", "diskio", "name", HOST),
        variable("interface", "Network interface", "net", "interface", HOST),
    ]},
    "panels": panels,
}

if __name__ == "__main__":
    path = ROOT / "projects/server-resources-overview.json"
    path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {path.name}: {len(panels)} panels")
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/scripts/dashboard_io.py

```python
"""Shared validation for Classic Grafana dashboard files (no external packages)."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")


class DashboardError(ValueError):
    pass


def load_dashboard(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DashboardError(f"{path}: cannot read JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DashboardError(f"{path}: dashboard must be a JSON object")
    if "dashboard" in data:
        data = data["dashboard"]
    if not isinstance(data, dict) or "panels" not in data:
        raise DashboardError(f"{path}: export Classic JSON with panels; V2/resource models are not converted")
    return data


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def walk_panels(panels):
    if not isinstance(panels, list):
        raise DashboardError("panels must be an array")
    for panel in panels:
        if not isinstance(panel, dict):
            raise DashboardError("each panel must be an object")
        yield panel
        if "panels" in panel:
            yield from walk_panels(panel["panels"])


def validate_dashboard(data):
    if not isinstance(data.get("uid"), str) or not UID_PATTERN.fullmatch(data["uid"]):
        raise DashboardError("uid must contain 1–40 letters, digits, underscores or hyphens")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise DashboardError("title must be a non-empty string")
    if data.get("id") is not None:
        raise DashboardError("dashboard id must be null or omitted; use import_dashboard.py to normalize an export")
    if type(data.get("version", 0)) is not int or data.get("version", 0) < 0:
        raise DashboardError("version must be a non-negative integer")
    if data.get("__inputs"):
        raise DashboardError("unresolved __inputs: import via UI or supply --datasource INPUT_NAME=TARGET_UID")
    ids = set()
    for panel in walk_panels(data.get("panels")):
        pid = panel.get("id")
        if type(pid) is not int or pid < 0:
            raise DashboardError("panel id must be a non-negative integer")
        if pid in ids:
            raise DashboardError(f"duplicate panel id: {pid}")
        ids.add(pid)
        if not isinstance(panel.get("type"), str) or not panel["type"]:
            raise DashboardError(f"panel {pid}: missing type")
        # Row nesting, repeated panels and third-party panel types are allowed.
    templating = data.get("templating", {})
    if not isinstance(templating, dict) or not isinstance(templating.get("list", []), list):
        raise DashboardError("templating.list must be an array")
    variables = set()
    for variable in templating.get("list", []):
        if not isinstance(variable, dict) or not isinstance(variable.get("name"), str):
            raise DashboardError("each variable must have a name")
        if variable["name"] in variables:
            raise DashboardError(f"duplicate variable: {variable['name']}")
        variables.add(variable["name"])
    for node in walk(data):
        ds = node.get("datasource")
        ref = ds.get("uid") if isinstance(ds, dict) else ds
        if isinstance(ref, str):
            match = VARIABLE.fullmatch(ref)
            if match:
                name = match[1] or match[2]
                if name not in variables and not name.startswith("__"):
                    raise DashboardError(f"datasource variable {name} is not declared in templating.list")


def validate_collection(entries):
    uids, titles = {}, {}
    for path, data in entries:
        try:
            validate_dashboard(data)
        except DashboardError as exc:
            raise DashboardError(f"{path}: {exc}") from exc
        for key, registry in ((data["uid"], uids), (data["title"].strip().casefold(), titles)):
            if key in registry:
                raise DashboardError(f"{path}: conflicting UID or title with {registry[key]}")
            registry[key] = path


def project_dashboards(directory, exclude=None):
    for path in sorted(Path(directory).rglob("*.json")):
        if exclude is None or path.resolve() != Path(exclude).resolve():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "panels" not in data:
                raise DashboardError(f"{path}: expected unwrapped Classic JSON; use import_dashboard.py")
            yield path, data
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/scripts/import_dashboard.py

```python
#!/usr/bin/env python3
"""Prepare a Classic export for provisioning, preserving panel IDs and queries."""
import argparse
import copy
import json
from pathlib import Path
import sys
import uuid

from dashboard_io import (
    ROOT, DashboardError, load_dashboard, project_dashboards,
    validate_collection, validate_dashboard, walk,
)


def parse_mappings(values):
    mappings = {}
    for value in values:
        key, sep, target = value.partition("=")
        if not sep or not key.strip() or not target.strip():
            raise DashboardError("use --datasource OLD_UID=NEW_UID or --datasource INPUT_NAME=NEW_UID")
        if key in mappings:
            raise DashboardError(f"duplicate datasource mapping: {key}")
        mappings[key] = target
    return mappings


def prepare_dashboard(original, mappings, uid=None, title=None):
    data = copy.deepcopy(original)
    substitutions = dict(mappings)
    for item in data.get("__inputs", []):
        if not isinstance(item, dict) or item.get("type") != "datasource":
            raise DashboardError("resolve non-datasource __inputs in Grafana UI, then export Classic JSON")
        name = item.get("name")
        if name not in mappings:
            raise DashboardError(f"missing --datasource {name}=TARGET_UID")
        substitutions[f"${{{name}}}"] = mappings[name]
        substitutions[f"${name}"] = mappings[name]
    for node in walk(data):
        ds = node.get("datasource")
        if isinstance(ds, str) and ds in substitutions:
            node["datasource"] = substitutions[ds]
        elif isinstance(ds, dict) and ds.get("uid") in substitutions:
            ds["uid"] = substitutions[ds["uid"]]
    for variable in data.get("templating", {}).get("list", []):
        if variable.get("type") == "datasource":
            current = variable.get("current", {})
            old = current.get("value")
            if isinstance(old, str) and old in substitutions:
                current.update(value=substitutions[old], text=substitutions[old])
                variable["options"] = []
                variable["refresh"] = 1
    data.pop("__inputs", None)
    data["id"] = None
    data["version"] = 1
    data["uid"] = uid or data.get("uid") or f"project-{uuid.uuid4().hex[:12]}"
    if title is not None:
        data["title"] = title
    validate_dashboard(data)
    return data


def save_dashboard(data, destination, directory, overwrite=False):
    directory = Path(directory).resolve()
    destination = Path(destination).resolve()
    if not destination.is_relative_to(directory) or destination.suffix != ".json":
        raise DashboardError("output must be a .json file inside projects/")
    if destination.exists() and not overwrite:
        raise DashboardError(f"{destination}: already exists; use --overwrite for an intentional update")
    entries = list(project_dashboards(directory, exclude=destination))
    validate_collection([*entries, (destination, data)])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w" if overwrite else "x", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Classic JSON export or API response with dashboard")
    parser.add_argument("--output", type=Path, help="destination under projects/; default projects/<uid>.json")
    parser.add_argument("--uid", help="override dashboard UID; panel IDs are preserved")
    parser.add_argument("--title", help="override dashboard title")
    parser.add_argument("--datasource", action="append", default=[], metavar="OLD=NEW_UID")
    parser.add_argument("--overwrite", action="store_true", help="allow updating the destination file")
    args = parser.parse_args()
    try:
        data = prepare_dashboard(load_dashboard(args.source), parse_mappings(args.datasource), args.uid, args.title)
        destination = args.output or ROOT / "projects" / f"{data['uid']}.json"
        save_dashboard(data, destination, ROOT / "projects", args.overwrite)
    except (DashboardError, OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared {destination} (UID: {data['uid']}). Grafana loads it into Projects within 30 seconds when this directory is mounted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/scripts/init_env.py

```python
#!/usr/bin/env python3
"""Create .env once, with generated secrets; never print or overwrite them."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
content = (root / ".env.example").read_text()
for name in ("GRAFANA_ADMIN_PASSWORD", "INFLUXDB_ADMIN_PASSWORD",
             "INFLUXDB_READ_PASSWORD", "INFLUXDB_WRITE_PASSWORD"):
    content = content.replace(f"{name}=\n", f"{name}={secrets.token_hex(24)}\n")
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(".env already exists; unchanged.")
else:
    with os.fdopen(fd, "w") as output:
        output.write(content)
    print("Created .env (0600). Set TELEGRAF_HOST and Grafana connection settings before starting.")
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/scripts/validate.py

```python
#!/usr/bin/env python3
"""Validate any number of Classic dashboards in projects/, including subfolders."""
import sys
import tomllib

from dashboard_io import ROOT, DashboardError, project_dashboards, validate_collection


def main():
    try:
        dashboards = list(project_dashboards(ROOT / "projects"))
        validate_collection(dashboards)
        tomllib.loads((ROOT / "monitoring/telegraf/telegraf.conf").read_text())
    except (DashboardError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {len(dashboards)} dashboard(s); JSON, unique UIDs/titles, nested panel IDs, datasource variables and Telegraf TOML.")
    print("Datasource connectivity, installed plugins and queries must be checked in Grafana.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/tests/test_import_dashboard.py

```python
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dashboard_io import DashboardError, load_dashboard, project_dashboards, validate_collection
from import_dashboard import parse_mappings, prepare_dashboard, save_dashboard


def dashboard(uid="example", title="Example"):
    return {"id": 12, "uid": uid, "title": title, "version": 8,
            "templating": {"list": []}, "panels": [
                {"id": 1, "type": "row", "panels": [
                    {"id": 2, "type": "table", "datasource": {"type": "prometheus", "uid": "old"},
                     "targets": [{"refId": "A", "datasource": "old", "expr": 'up{job="old"}'}]}
                ]}], "annotations": {"list": [{"datasource": {"type": "prometheus", "uid": "old"}}]}}


class ImportDashboardTests(unittest.TestCase):
    def test_nested_panel_target_annotation_mapping_preserves_query_and_ids(self):
        source = dashboard()
        before = copy.deepcopy(source)
        result = prepare_dashboard(source, {"old": "new"})
        self.assertEqual(source, before)
        panel = result["panels"][0]["panels"][0]
        self.assertEqual([result["panels"][0]["id"], panel["id"]], [1, 2])
        self.assertEqual(panel["datasource"], {"type": "prometheus", "uid": "new"})
        self.assertEqual(panel["targets"][0]["datasource"], "new")
        self.assertEqual(panel["targets"][0]["expr"], 'up{job="old"}')
        self.assertEqual(result["annotations"]["list"][0]["datasource"]["uid"], "new")
        self.assertIsNone(result["id"])
        self.assertEqual(result["version"], 1)

    def test_multiple_external_inputs_are_mapped_independently(self):
        source = dashboard()
        source["__inputs"] = [{"name": "DS_ONE", "type": "datasource"}, {"name": "DS_TWO", "type": "datasource"}]
        source["panels"][0]["panels"][0]["datasource"]["uid"] = "${DS_ONE}"
        source["annotations"]["list"][0]["datasource"]["uid"] = "$DS_TWO"
        result = prepare_dashboard(source, {"DS_ONE": "one", "DS_TWO": "two"})
        self.assertEqual(result["panels"][0]["panels"][0]["datasource"]["uid"], "one")
        self.assertEqual(result["annotations"]["list"][0]["datasource"]["uid"], "two")
        self.assertNotIn("__inputs", result)

    def test_unresolved_inputs_and_variables_are_rejected(self):
        source = dashboard()
        source["__inputs"] = [{"name": "DS_ONE", "type": "datasource"}]
        with self.assertRaisesRegex(DashboardError, "missing --datasource"):
            prepare_dashboard(source, {})
        source.pop("__inputs")
        source["panels"][0]["panels"][0]["datasource"]["uid"] = "${UNDECLARED}"
        with self.assertRaisesRegex(DashboardError, "not declared"):
            prepare_dashboard(source, {})

    def test_datasource_variable_and_query_variable_mappings(self):
        source = dashboard()
        source["templating"]["list"] = [
            {"name": "DS_MAIN", "type": "datasource", "query": "prometheus", "current": {"text": "Old", "value": "old"}, "options": [{"value": "old"}]},
            {"name": "host", "type": "query", "datasource": {"type": "prometheus", "uid": "old"}, "query": "label_values(up, instance)"}]
        source["panels"][0]["panels"][0]["datasource"]["uid"] = "${DS_MAIN}"
        result = prepare_dashboard(source, {"old": "new"})
        variable = result["templating"]["list"][0]
        self.assertEqual(variable["current"]["value"], "new")
        self.assertEqual(variable["options"], [])
        self.assertEqual(result["templating"]["list"][1]["datasource"]["uid"], "new")
        self.assertEqual(result["panels"][0]["panels"][0]["datasource"]["uid"], "${DS_MAIN}")

    def test_classic_and_api_exports_supported_but_v2_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            for data in (dashboard(), {"dashboard": dashboard(), "meta": {"folderTitle": "Original"}}):
                path.write_text(json.dumps(data))
                self.assertEqual(load_dashboard(path), dashboard())
            path.write_text(json.dumps({"kind": "Dashboard", "spec": {"elements": {}}}))
            with self.assertRaisesRegex(DashboardError, "Classic"):
                load_dashboard(path)

    def test_no_fixed_count_and_custom_panel_types_allowed(self):
        validate_collection([])
        entries = []
        for i in range(4):
            data = prepare_dashboard(dashboard(f"project-{i}", f"Project {i}"), {})
            data["panels"][0]["panels"][0]["type"] = "third-party-panel"
            entries.append((f"{i}.json", data))
        validate_collection(entries)

    def test_collisions_include_nested_files_and_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = prepare_dashboard(dashboard(), {})
            save_dashboard(data, root / "team/one.json", root)
            for other in (prepare_dashboard(dashboard(title="Different"), {}), prepare_dashboard(dashboard(uid="different"), {})):
                with self.assertRaisesRegex(DashboardError, "conflicting"):
                    save_dashboard(other, root / "two.json", root)
            self.assertEqual(len(list(project_dashboards(root))), 1)

    def test_existing_file_requires_overwrite_and_survives_failed_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / "dashboard.json"
            data = prepare_dashboard(dashboard(), {})
            save_dashboard(data, dest, root)
            before = dest.read_bytes()
            with self.assertRaisesRegex(DashboardError, "already exists"):
                save_dashboard(data, dest, root)
            invalid = copy.deepcopy(data)
            invalid["panels"][0]["panels"][0]["id"] = 1
            with self.assertRaisesRegex(DashboardError, "duplicate panel"):
                save_dashboard(invalid, dest, root, overwrite=True)
            self.assertEqual(before, dest.read_bytes())
            data["title"] = "Updated"
            save_dashboard(data, dest, root, overwrite=True)
            self.assertEqual(json.loads(dest.read_text())["title"], "Updated")

    def test_outside_projects_and_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            root.mkdir()
            outside = Path(directory) / "elsewhere"
            outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            for path in (outside / "bad.json", root / "link/bad.json", root / "bad.yaml"):
                with self.assertRaisesRegex(DashboardError, "inside projects"):
                    save_dashboard(prepare_dashboard(dashboard(), {}), path, root)

    def test_input_validation_and_uid_generation(self):
        for value in ("no-equals", "=target", "source="):
            with self.assertRaises(DashboardError):
                parse_mappings([value])
        with self.assertRaises(DashboardError):
            parse_mappings(["a=b", "a=c"])
        source = dashboard()
        source.pop("uid")
        result = prepare_dashboard(source, {})
        self.assertTrue(result["uid"].startswith("project-"))
        source["__inputs"] = [{"type": "constant", "name": "OTHER"}]
        with self.assertRaisesRegex(DashboardError, "non-datasource"):
            prepare_dashboard(source, {})
```

### /Users/mrsadman/Projects/parser_avito/graphana-skynet-dashboards/tests/test_server_dashboard.py

```python
import json
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = {
    "cpu": ({"usage_user", "usage_system", "usage_idle", "usage_iowait"}, {"host", "cpu"}),
    "mem": ({"used", "available", "total", "used_percent"}, {"host"}),
    "swap": ({"used", "free", "total", "used_percent"}, {"host"}),
    "disk": ({"used", "free", "total", "used_percent", "inodes_used", "inodes_free"}, {"host", "device", "path"}),
    "diskio": ({"read_bytes", "write_bytes", "read_time", "write_time"}, {"host", "name"}),
    "net": ({"bytes_sent", "bytes_recv", "packets_sent", "packets_recv", "err_in", "err_out", "drop_in", "drop_out"}, {"host", "interface"}),
    "system": ({"load1", "load5", "load15", "n_users", "uptime"}, {"host"}),
    "processes": ({"total", "running", "sleeping", "blocked", "zombies"}, {"host"}),
}


class ServerDashboardTests(unittest.TestCase):
    def test_metric_queries_and_telegraf_contract(self):
        server = json.loads((ROOT / "projects/server-resources-overview.json").read_text())
        assert server["time"] == {"from": "now-30m", "to": "now"}
        assert server["refresh"] == "30s"
        variables = {v["name"]: v for v in server["templating"]["list"]}
        for name in ("host", "device", "path", "diskio_device", "interface"):
            assert variables[name]["multi"] and variables[name]["includeAll"]
            assert variables[name]["allValue"] == ".*"
        assert variables["interval"]["auto_min"] == "10s"
        fields_seen = {m: set() for m in SCHEMA}
        for p in server["panels"]:
            assert p["datasource"] == {"type": "influxdb", "uid": "${DS_INFLUXDB}"}
            assert p["fieldConfig"]["defaults"]["unit"]
            assert p["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["value"] is None
            for t in p["targets"]:
                q = t["query"]
                assert t["datasource"] == p["datasource"]
                assert t["rawQuery"] and t["resultFormat"] == "time_series"
                assert '$timeFilter' in q and 'time($interval)' in q and 'fill(null)' in q
                assert '"host" =~ /^${host:regex}$/' in q
                measurement = re.search(r'FROM "(\w+)"', q)[1]
                allowed_fields, allowed_tags = SCHEMA[measurement]
                fields = set(re.findall(r'(?:mean|last)\("(\w+)"\)', q))
                assert fields <= allowed_fields, (measurement, fields)
                fields_seen[measurement].update(fields)
                tags = set(re.findall(r'"(\w+)"', q.split('GROUP BY', 1)[1]))
                assert "host" in tags and tags <= allowed_tags
                assert set(re.findall(r'\[\[tag_(\w+)\]\]', t["alias"])) == tags
                if measurement in {"net", "diskio"}:
                    assert 'non_negative_derivative(last(' in q and ', 1s)' in q
                for v in re.findall(r'\$\{(\w+)(?::\w+)?\}', q):
                    assert v in variables
        for measurement, (fields, _) in SCHEMA.items():
            assert fields_seen[measurement] == fields, (measurement, fields - fields_seen[measurement])
        config = tomllib.loads((ROOT / "monitoring/telegraf/telegraf.conf").read_text())
        assert set(config["inputs"]) == set(SCHEMA)
        assert config["agent"]["interval"] == "10s"
        assert config["outputs"]["influxdb"][0]["retention_policy"] == "telegraf"
```
