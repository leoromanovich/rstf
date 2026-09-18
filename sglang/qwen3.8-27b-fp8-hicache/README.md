# qwen3.8-27b-fp8-hicache

Модель: `Qwen3.8-27B-FP8`. Одна GPU 48 GiB; 8 concurrent requests, context 32768, chunk 2048. База использует HTTP и штатную трассировку SGLang. Custom gRPC images, точные KV-events и custom tracing patches исключены из запуска; соответствующие старые скрипты сохранены как исходники. MTP EAGLE 3/1/4 + ReplaySSM сохранён из проверенного C8 профиля; HTTP migration требует повторного throughput/quality benchmark. GPU memory budget сохраняет запас под hybrid state.

Throughput budgets: `tp-size=1, dp-size=1, context-length=32768, max-running-requests=8, chunked-prefill-size=2048`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

Thinking включён, `reasoning_effort=medium` задан явно. В исходном шаблоне default — `xhigh`; поддерживаются `low`, `medium`, `xhigh`. [Chat template Qwen3.8](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/main/chat_template.jinja).

## Cache tiers

| Вариант | Compose files |
|---|---|
| Без offloading | `docker-compose.yaml` |
| RAM | база + `compose.ram.yaml` |
| RAM + SSD | база + `compose.ssd.yaml` |

Оба overlay независимо расширяют базу. Совместное применение RAM и SSD overlay не требуется.
Общие engine flags находятся в folded `entrypoint: >-`; overlay задаёт только `command: >-`.
Docker передаёт итоговый `entrypoint + command` единым argv. Константы редактируются в Compose.

HiCache budget задаётся на процесс/rank: проверь сумму по TP/DP и запас host RAM. File backend использует LRU в v0.5.19; размеры — `Gi/T`, без `GiB/GB`. Лимит каждого rank не заменяет общую filesystem quota. SSD namespaces отделены от старых cache entries.

## Запуск

API SMG — `127.0.0.1:30001`; engine — `sglang:30000` внутри Docker.
Collector экспортирует метрики движка и SMG на `127.0.0.1:9234/metrics`.
Внутренний OTLP transport — `otel-collector:4317/4318`; локальный Jaeger UI (где включён) — `127.0.0.1:16686`.

1. Проверь bind paths, GPU и cache budgets в Compose; подготовь каталоги и SSD quota.
2. Скопируй `.env.example` в защищённый локальный `.env`; задай API/admin keys и внешний OTLP endpoint, где требуется. Константы в env не выносятся.
3. Через CC feature override вызови `inference-recipe-control sglang/qwen3.8-27b-fp8-hicache config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[SGLang #36935](https://github.com/sgl-project/sglang/issues/36935): деградация reuse hybrid-cache при несогласованных размерах KV/Mamba; сохранены `max-mamba-cache-size=35`, BF16 GDN и FP8 KV. [SGLang #36333](https://github.com/sgl-project/sglang/issues/36333): streaming disconnect требует отдельной проверки на v0.5.19. [Qwen #216](https://github.com/QwenLM/Qwen3.8/issues/216): пустые ответы с xhigh.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.

Исторические `Dockerfile.*`, `patch_*`, `tracing_bridge.py`, `inspect_cache.py`, `disconnect_probe.py` относятся к custom gRPC пути и текущим Compose не используются. `compose.tracing.yaml`/`compose.trace-ui.yaml` сохранены как совместимые aliases; `compose.external.yaml` переключает экспорт во внешний OTLP.
