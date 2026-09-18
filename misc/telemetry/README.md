# Единый lifecycle LLM recipes

Рецепты: [матрица вариантов и ограничений](RECIPE-AUDIT.md). Контракт: [AGENTS.md](../../AGENTS.md).

- SMG API: `127.0.0.1:30001/v1`.
- Engine API/metrics: `<service>:30000`, только Docker bridge.
- Все метрики SMG/engine: `127.0.0.1:9234/metrics`, агрегируются существующим OTel Collector.
- OTLP gRPC/HTTP `4317/4318` — внутренний protocol transport; на хост не публикуется.
- Локальный Jaeger UI: `127.0.0.1:16686`. External-рецепты отправляют traces на заданный TLS endpoint.

Константы и пути находятся в Compose. `.env` хранит ключи и внешний telemetry endpoint.
Collector отбрасывает содержимое сообщений из traces; API keys не печатаются lifecycle-командами.
SMG/Collector не получают GPU. Образы закреплены digest; локальных build в рецептах нет.

## Nix / CC

Из CC, где feature `compose-recipes-contract` подключает рабочую копию:

```bash
./cc feature compose-recipes-contract run nyashkimyashki-inference-recipe-control sglang/qwen3.8-27b-fp8-hicache config --cache ssd
./cc feature compose-recipes-contract check
```

App принимает:

```text
inference-recipe-control <catalog-path> <action> --cache none|ram|ssd [--variant base|mtp] [--env-file /secure/recipe.env]
```

`config` использует `.env.example` при отсутствии явного файла, выводит только результат проверки.
`RECIPE_ROOT=/srv/nyashkimyashki` выбирает checkout на целевом host для runtime actions: относительные bind paths должны разрешаться вне read-only Nix store. Для Qwen вспомогательных действий также можно задать `QWEN38_CONFIG_DIR`.
`preflight` проверяет выбранный tier на целевом Linux GPU host без запуска контейнеров.
`up|restart|stop|down` требуют `RECIPE_CONFIRM=mutate-inference`; `up` передаёт `--no-build`.
`build --allow-local-build` допускается только после отдельного решения пользователя; стандартный Compose не содержит build-секций.
`--experiment` создаёт временный локальный override с `restart: "no"` для всех сервисов. Штатная policy — `unless-stopped`.
Для остановки используй тот же cache/variant, с которым запускал стек. При смене tier сначала останови предыдущий стек.

## Compose merge

Общие engine flags записаны в `entrypoint: >-`, по одному флагу на строку.
База задаёт `command: []`; независимые `compose.ram.yaml` / `compose.ssd.yaml` добавляют только cache flags через `command: >-`.
Итоговый argv — `entrypoint + command`; оба поля проверяются через Compose JSON.
MTP Gemma включается отдельным overlay и выбором сервиса в controller.

## Проверки

Nix check `recipe-telemetry` запускает `validate.py`: Compose schema/argv, pinned images/no build,
reasoning defaults, base/RAM/SSD separation, internal ports, metrics, restart и lifecycle regression tests.
Для проверки traces: `trace-check --model <served-id>`; передай ключ через `TRACE_API_KEY`.
Локальный mode проверяет Jaeger; external mode подтверждает экспорт без чтения удалённого backend.
GPU workload acceptance выполняется отдельно: обычный запрос без reasoning overrides, tool/vision,
cold/warm cache, SSD restore, cache pressure и throughput под конкурентной нагрузкой.
