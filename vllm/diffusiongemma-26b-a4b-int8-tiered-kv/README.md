# diffusiongemma-26b-a4b-int8-tiered-kv

Модель: `diffusiongemma-26B-A4B-it-INT8-dynamic`. A100 80 GB, INT8 compressed-tensors checkpoint, vLLM 0.26.0 cu129. `performance-mode=throughput`, batch 8192, 4 concurrent sequences при context 65536. Небольшой running limit обусловлен памятью diffusion sampler/FP32 head. Исторический RTX 4090 canary исключён из параметров deployment; его GPU acceptance не переносится на A100.

Throughput budgets: `max-model-len=65536, max-num-seqs=4, max-num-batched-tokens=8192`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

`enable_thinking=true` задан явно: default processor/template оставляет thinking выключенным. У модели нет отдельных effort levels; `medium` задать нельзя. [Google: thinking у DiffusionGemma](https://ai.google.dev/gemma/docs/diffusiongemma/inference-diffusiongemma-with-hf), [vLLM recipe](https://github.com/vllm-project/recipes/blob/main/models/Google/diffusiongemma-26B-A4B-it.yaml).

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

API SMG — `127.0.0.1:30001`; engine — `diffusiongemma:30000` внутри Docker.
Collector экспортирует метрики движка и SMG на `127.0.0.1:9234/metrics`.
Внутренний OTLP transport — `otel-collector:4317/4318`; локальный Jaeger UI (где включён) — `127.0.0.1:16686`.

1. Проверь bind paths, GPU и cache budgets в Compose; подготовь каталоги и SSD quota.
2. Скопируй `.env.example` в защищённый локальный `.env`; задай API/admin keys и внешний OTLP endpoint, где требуется. Константы в env не выносятся.
3. Через CC feature override вызови `inference-recipe-control vllm/diffusiongemma-26b-a4b-int8-tiered-kv config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[vLLM #51579](https://github.com/vllm-project/vllm/issues/51579): native CPU offload оставляет mmap после аварийного выхода; private IPC и cleanup-wrapper ограничивают последствие контейнером. Для DiffusionGemma cold/warm HMA restore на этом checkpoint требует GPU acceptance.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
