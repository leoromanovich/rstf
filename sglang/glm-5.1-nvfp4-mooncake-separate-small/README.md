# glm-5.1-nvfp4-mooncake-separate-small

Модель: `/models/GLM-5.1-NVFP4`. Throughput: TP8/DP8 с DP attention и балансировкой по tokens. Убраны старый `schedule-conservativeness=3.333`, дубли флагов и ручной `index_topk_pattern`; используются defaults закреплённого релиза. NVFP4/TRTLLM требует совместимых Blackwell GPU. Mooncake master/store запускаются только с SSD overlay. RAM tier использует локальный HiCache. `mooncake-host` сохраняет историческое имя каталога; соединения переведены в Docker bridge. Для separate-вариантов проверь отсутствие конфликтов подсети 172.29.0.0/24.

Throughput budgets: `tp-size=8, dp-size=8, context-length=202752, max-running-requests=128, chunked-prefill-size=65536`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

`enable_thinking=true` задан явно. Шаблон включает thinking по умолчанию; отдельных уровней `low/medium/high` у GLM-5.1 нет. [Шаблон GLM-5.1](https://huggingface.co/zai-org/GLM-5.1/blob/main/chat_template.jinja), [high-throughput DPA recipe](https://github.com/sgl-project/sglang/blob/v0.5.19/docs/src/snippets/autoregressive/glm-51-deployment.jsx).

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
3. Через CC feature override вызови `inference-recipe-control sglang/glm-5.1-nvfp4-mooncake-separate-small config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[SGLang #26357](https://github.com/sgl-project/sglang/issues/26357): зависания GLM-5.1 TP8 + HiCache + EAGLE под KV pressure. [SGLang #28771](https://github.com/sgl-project/sglang/issues/28771): ухудшение EAGLE acceptance с Mooncake/HiCache. Поэтому speculative decoding исключён из базы и обоих cache tiers.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
