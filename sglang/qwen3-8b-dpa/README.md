# qwen3-8b-dpa

Модель: Qwen/Qwen3-8B-FP8. SGLang 0.5.19, две GPU, TP2/DP2 с DP attention. Throughput: 32 running requests суммарно и prefill chunk 8192; старый завышенный schedule-conservativeness удалён.

Throughput budgets: `tp=2, dp=2, context-length=32768, max-running-requests=32, chunked-prefill-size=8192`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

`enable_thinking=true` задан явно. В шаблоне Qwen3-8B thinking включён по умолчанию; native effort levels отсутствуют. [Tokenizer/chat template](https://huggingface.co/Qwen/Qwen3-8B/blob/main/tokenizer_config.json).

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
3. Через CC feature override вызови `inference-recipe-control sglang/qwen3-8b-dpa config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

Проверены model/HiCache issues и [release v0.5.19](https://github.com/sgl-project/sglang/releases/tag/v0.5.19). Отдельного подтверждённого блокера для Qwen3-8B + File HiCache в проверенных issues не найдено; это не подтверждает GPU совместимость. [Общий streaming disconnect issue #36333](https://github.com/sgl-project/sglang/issues/36333) требует cancel/pressure acceptance.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
