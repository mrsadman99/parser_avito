## Работа через Docker

Для просмотра логов через Grafana предусмотрен отдельный Docker Compose с Loki
и Alloy: [настройка мониторинга](MONITORING.md). Он работает и с парсером вне Docker.

Docker **рекомендуется**, если:

- парсер работает **24/7**
- используется **VPS**
- нужен стабильный фоновый режим без привязки к терминалу
- планируется масштабирование или запуск нескольких воркеров

Перед первым запуском **обязательно** настройте файл `config.toml`.

---

### Основные команды (Makefile)

```bash
make build    # собрать Docker-образ
make run      # запустить контейнер в фоне
make restart  # перезапустить контейнер
make rebuild  # полная пересборка: stop → build → run
make stop     # остановить и удалить контейнер
make logs     # посмотреть логи контейнера
make shell    # зайти внутрь контейнера (bash)
make clean    # удалить контейнер и Docker-образ
```

💡 Все команды являются обёртками над docker / docker-compose
и описаны в Makefile. При необходимости их легко адаптировать под себя.

### Запуск через docker-compose

```bash
touch database.db
docker-compose up -d
```

#### Podman / podman-compose

При использовании podman-compose рекомендуется установка из ветки main,
так как в релизных версиях присутствуют баги:

https://github.com/containers/podman-compose/issues/1275

### VPS
💡 Подходящий VPS по адекватной цене можно арендовать здесь: [beget](https://beget.com/p2175639)


🎥 Видео с разбором покупки сервера, первичной настройки и запуска парсера:
https://youtu.be/_XQW2ApNwiQ
