ifeq ($(OS),Windows_NT)
	CURDIR := $(shell cd)
	NULL_OUT := NUL
	TRUE := rem
else
	CURDIR := $(shell pwd)
	NULL_OUT := /dev/null
	TRUE := true
endif

IMAGE_NAME = parser_avito:latest
CONTAINER_NAME = parser_avito_container

.PHONY: build run restart stop logs shell clean rebuild

MONITORING_COMPOSE = docker compose --env-file monitoring/.env -f docker-compose.monitoring.yml
.PHONY: monitoring-init monitoring-up monitoring-down monitoring-logs monitoring-check

monitoring-init:
	python3 scripts/init_monitoring.py

monitoring-up:
	$(MONITORING_COMPOSE) up -d

monitoring-down:
	$(MONITORING_COMPOSE) down

monitoring-logs:
	$(MONITORING_COMPOSE) logs -f --tail=100

monitoring-check:
	$(MONITORING_COMPOSE) config --quiet
	$(MONITORING_COMPOSE) run --rm --no-deps loki -config.file=/etc/loki/config.yml -verify-config=true
	$(MONITORING_COMPOSE) run --rm --no-deps alloy validate /etc/alloy/config.alloy
	$(MONITORING_COMPOSE) run --rm --no-deps log-gateway nginx -t

# 🏗️ Сборка Docker-образа
build:
	docker build -t $(IMAGE_NAME) .

# ▶️ Запуск контейнера в фоне
run:
	docker run -d \
		--name $(CONTAINER_NAME) \
		-v $(CURDIR):/app \
		$(IMAGE_NAME)

# 🔄 Перезапуск контейнера (если уже запущен)
restart: stop run

# 🧱 Полная пересборка: stop → build → run
rebuild: stop build run

# 🧹 Остановка и удаление контейнера
stop:
	@docker stop $(CONTAINER_NAME) >$(NULL_OUT) 2>&1 || $(TRUE)
	@docker rm $(CONTAINER_NAME) >$(NULL_OUT) 2>&1 || $(TRUE)
	@echo Container stopped and removed.

# 📜 Просмотр логов контейнера
logs:
	docker logs -f $(CONTAINER_NAME)

# 🐚 Подключение внутрь контейнера
shell:
	docker exec -it $(CONTAINER_NAME) bash

# 🧽 Полная очистка (контейнер + образ)
clean: stop
	@docker rmi $(IMAGE_NAME) >$(NULL_OUT) 2>&1 || $(TRUE)
	@echo Image removed.
