# Grafana + Loki + Alloy

Мониторинг запускается отдельным Docker Compose и читает логи из папки проекта.
Парсер может работать непосредственно на сервере или в контейнере на том же
Docker-хосте. Для отдельного сервера мониторинга понадобится Alloy на сервере
парсера и защищённое сетевое подключение к Loki; текущая конфигурация рассчитана
на один сервер.

```text
парсер → logs/events.jsonl → Alloy → Loki → Grafana
```

## Запуск

Команды выполняются из корня проекта. Нужны Docker Engine и Docker Compose v2+.

```bash
make monitoring-init
make monitoring-check
make monitoring-up
```

`monitoring-init` создаёт `monitoring/.env` со случайным паролем и правами `0600`.
Повторный запуск сохраняет существующий файл. Он исключён из Git и Docker build.
Настройки без секретов находятся в `monitoring/.env.example`.

Перезапусти парсер с обновлённым кодом, чтобы появился `logs/events.jsonl`.
При запуске через основной `docker-compose.yml` папка `./logs` уже проброшена
в `/app/logs`. Для образа с обновлённым кодом можно выполнить:

```bash
docker build -t avito-parser-local .
# Укажи image: avito-parser-local в сервисе parser_avito своего docker-compose.yml.
```

Готовый внешний образ `ghcr.io/duff89/parser_avito:latest` может не содержать этих
изменений: одного подключения папки логов к старому образу недостаточно.

Открой **http://localhost:3001**, войди с логином `admin` и паролем
`GRAFANA_ADMIN_PASSWORD` из `monitoring/.env`.
Datasource **Avito Loki** и дашборд **Avito → Avito — логи** создаются автоматически.
Дашборд обновляется каждые 10 секунд; есть выбор сервера, алгоритма, уровня и поиск
по тексту или ID объявления. Панель общего журнала учитывает выбранные алгоритмы;
три отдельные панели всегда показывают свой алгоритм.

Для доступа к серверу с компьютера:

```bash
ssh -L 3001:127.0.0.1:3001 user@server
```

После этого адрес в браузере также `http://localhost:3001`.

## Настройки и команды

В `monitoring/.env`:

| Параметр | Назначение |
| --- | --- |
| `AVITO_LOG_DIR=./logs` | Папка логов на Docker-хосте. Относительный путь считается от корня проекта; можно указать абсолютный |
| `AVITO_INSTANCE=avito-server` | Постоянное имя сервера в фильтре Grafana |
| `GRAFANA_BIND_ADDRESS=127.0.0.1` | Адрес, на котором доступна Grafana |
| `GRAFANA_PORT=3001` | Внешний порт Grafana |
| `GRAFANA_ROOT_URL=http://localhost:3001/` | Полный адрес Grafana для пользователей |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | Учётная запись администратора при первом запуске |

Например, для доступа по IP сервера установи `GRAFANA_BIND_ADDRESS=0.0.0.0`
и `GRAFANA_ROOT_URL=http://IP_СЕРВЕРА:3001/`. Для доступа через интернет используй
HTTPS на существующем reverse proxy; upstream — `http://127.0.0.1:3001`,
а `GRAFANA_ROOT_URL` — внешний HTTPS-адрес. Loki и Alloy не публикуют порты наружу;
Loki работает без аутентификации только внутри сети этого Compose.

Если парсер работает в Docker и меняется папка логов, измени также bind mount
`/app/logs` в его Compose: обе стороны должны видеть одну и ту же папку.
Для Linux с SELinux подключение логов использует общую метку `z`.

```bash
make monitoring-up       # запуск / применение изменений Compose и .env
make monitoring-logs     # логи самих Grafana, Loki и Alloy
make monitoring-check    # проверка Compose, конфигураций Loki и Alloy их бинарниками
make monitoring-down     # остановка; история и настройки в томах сохраняются
```

Полная команда вместо Make:

```bash
docker compose --env-file monitoring/.env -f docker-compose.monitoring.yml up -d
```

После изменения `config.alloy` или `monitoring/loki/config.yml` перезапусти сервис:

```bash
docker compose --env-file monitoring/.env -f docker-compose.monitoring.yml restart alloy loki
```

Файлы дашборда Grafana перечитывает автоматически. Источник данных применяется
при запуске Grafana. Пароль из окружения задаёт начального администратора;
после первого запуска менять его следует через Grafana, а не редактированием `.env`.

## Какие события собираются

В приложении добавлен `logs/events.jsonl`: одно событие — одна строка JSON.
Поля: `timestamp` с часовым поясом, `level`, `subsystem`, `module`, `function`,
`line`, `message`, `exception`. Многострочный traceback сохраняется внутри
одного события. Произвольные `logger.bind(...)` данные в JSON не копируются;
действующая маскировка токенов и авторизации прокси применяется также здесь.

| `subsystem` | События |
| --- | --- |
| `scanning` | Раунды, страницы выдачи, фильтры, сохранение и обновление карточек |
| `notifications` | Отправки, повторные попытки, ошибки мессенджеров и скачивание фото |
| `blocking` | HTTP/Camoufox, cookies/SPFA, смена IP, tinyproxy и ADB из процесса парсера |
| `general` | Остальные сообщения Loguru в процессе парсера |

Текстовые `app.log`, `scanning.log`, `notifications.log`, `blocking.log` остаются.
Alloy читает только `events.jsonl`, поэтому копии одного сообщения из разных
текстовых файлов не увеличивают счётчики. Сырые `adb.log`, `tinyproxy.log`, stdout
веб-сервера и старые текстовые архивы автоматически не импортируются.

Примеры для **Explore → Avito Loki**:

```logql
{service_name="parser_avito"}
{service_name="parser_avito", subsystem="blocking"}
{service_name="parser_avito", subsystem="notifications", level=~"error|critical"}
{service_name="parser_avito"} |= "8258446852"
{service_name="parser_avito"} | json | function="_refresh_ad"
```

Индексируемые метки — имя приложения, job, сервер, алгоритм и уровень.
ID объявлений и URL остаются в тексте/JSON, чтобы не создавать отдельный поток
Loki на каждое объявление.

## Хранение и перезапуски

- Loki хранит историю **7 дней** на локальном диске Docker-хоста, в томе
  `loki-data`. Срок задан `retention_period` и `max_query_lookback` в его конфиге.
- `grafana-data` сохраняет пользователей и настройки Grafana.
- `alloy-data` сохраняет позиции чтения; штатный перезапуск продолжает чтение
  с сохранённого смещения. Не удаляй этот том для обычного перезапуска.
- JSON-файл ротируется приложением по 5 МБ, архивы хранятся 5 дней, как текстовые
  журналы. Alloy следует за активным файлом. Архивы автоматически не перечитываются:
  при длительной остановке Alloy события, успевшие уйти в архив, могут отсутствовать
  в Loki. Доставка после аварий не гарантирует строго однократную запись.
- `monitoring-down` сохраняет тома. Команда `down -v` удалит историю,
  позиции и пользователей Grafana; для обычной остановки она не нужна.

## Если в Grafana пусто

1. Проверь, что обновлённый парсер работает и `logs/events.jsonl` увеличивается.
2. Проверь `AVITO_LOG_DIR`: каталог должен существовать на Docker-хосте.
3. Выполни `make monitoring-logs`; ищи ошибки чтения файла или отправки в Loki.
4. В Explore выбери `Avito Loki`, запрос `{service_name="parser_avito"}`,
   период «последние 24 часа», убери фильтр текста.
5. Проверь часы сервера: время события берётся из JSON, а не из момента получения.

Документация компонентов: [чтение файлов Alloy](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/),
[обработка JSON и времени](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/),
[хранение Loki](https://grafana.com/docs/loki/latest/operations/storage/retention/),
[автоматическая настройка Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/).
