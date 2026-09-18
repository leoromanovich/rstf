# gemma4-26b-a4b-tiered-kv

Модель: `gemma-4-26B-A4B-it`. A100 80 GB, BF16 26B-A4B, vLLM 0.26.0 cu129. `performance-mode=throughput`, async scheduling, 24 sequences, batch 8192, context 131072. Model mount read-only, HF_HUB_OFFLINE=1. MTP: добавь `--variant mtp` в lifecycle; controller выбирает gemma4-mtp и переключает SMG/metrics. Прямой Compose: добавь `-f compose.mtp.yaml --profile mtp` и явно выбери `gemma4-mtp smg otel-collector jaeger`; одновременно оба GPU-сервиса не запускай.

Throughput budgets: `tensor-parallel-size=1, max-model-len=131072, max-num-seqs=24, max-num-batched-tokens=8192`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

`enable_thinking=true` задан явно. Default Gemma 4 chat template выключает thinking. Отдельного `medium` нет; используется доступный переключатель. [vLLM Gemma 4 chat template](https://github.com/vllm-project/vllm/blob/v0.26.0/examples/tool_chat_template_gemma4.jinja).

## Cache tiers

| Вариант | Compose files |
|---|---|
| Без offloading | `docker-compose.yaml` |
| RAM | база + `compose.ram.yaml` |
| RAM + SSD | база + `compose.ssd.yaml` |

Оба overlay независимо расширяют базу. Совместное применение RAM и SSD overlay не требуется.
Общие engine flags находятся в folded `entrypoint: >-`; overlay задаёт только `command: >-`.
Docker передаёт итоговый `entrypoint + command` единым argv. Константы редактируются в Compose.

RAM: native OffloadingConnector. SSD: TieringOffloadingSpec с filesystem tier `/kv-cache`, 32 read / 16 write threads. `PYTHONHASHSEED=0`, private IPC, cleanup только `vllm_offload_*.mmap` в приватном `/dev/shm`. SSD должен быть отдельным filesystem/project quota; backend не ограничивает общий объём сам. Для Gemma подготовь quota 2 TiB и минимум 512 GiB free.

## Запуск

API SMG — `127.0.0.1:30001`; engine — `gemma4:30000` внутри Docker.
Collector экспортирует метрики движка и SMG на `127.0.0.1:9234/metrics`.
Внутренний OTLP transport — `otel-collector:4317/4318`; локальный Jaeger UI (где включён) — `127.0.0.1:16686`.

1. Проверь bind paths, GPU и cache budgets в Compose; подготовь каталоги и SSD quota.
2. Скопируй `.env.example` в защищённый локальный `.env`; задай API/admin keys и внешний OTLP endpoint, где требуется. Константы в env не выносятся.
3. Через CC feature override вызови `inference-recipe-control vllm/gemma4-26b-a4b-tiered-kv config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[vLLM #51579](https://github.com/vllm-project/vllm/issues/51579): cleanup CPU mmap при аварии. [vLLM #48503](https://github.com/vllm-project/vllm/issues/48503): MTP graph-capture failure. MTP остаётся отдельным opt-in вариантом; базовый throughput рецепт без speculation.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
