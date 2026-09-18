# kimi-k2.6-dep8-eagle3

Модель: `Kimi-K2.6`. Высокая загрузка обеспечивается batching и prefix caching. vLLM обновлён до 0.26.0; `performance-mode=throughput`. EAGLE3 исключён из default из-за structured-output regression; историческое имя каталога сохранено. TP1/DP8/EP, text-only, до 96 последовательностей суммарно. RAM budget 100 GiB на DP replica, суммарно до 800 GiB плюс headroom.

Throughput budgets: `tensor-parallel-size=1, data-parallel-size=8, max-model-len=262144, max-num-seqs=12, max-num-batched-tokens=32768`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

`thinking=true` задан явно. Исходный шаблон включает reasoning; отдельного уровня `medium` у Kimi-K2.6 нет. [Шаблон Kimi-K2.6](https://huggingface.co/moonshotai/Kimi-K2.6/blob/main/chat_template.jinja).

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

API SMG — `127.0.0.1:30001`; engine — `vllm-kimi-k26:30000` внутри Docker.
Collector экспортирует метрики движка и SMG на `127.0.0.1:9234/metrics`.
Внутренний OTLP transport — `otel-collector:4317/4318`; локальный Jaeger UI (где включён) — `127.0.0.1:16686`.

1. Проверь bind paths, GPU и cache budgets в Compose; подготовь каталоги и SSD quota.
2. Скопируй `.env.example` в защищённый локальный `.env`; задай API/admin keys и внешний OTLP endpoint, где требуется. Константы в env не выносятся.
3. Через CC feature override вызови `inference-recipe-control vllm/kimi-k2.6-dep8-eagle3 config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[SGLang #28528](https://github.com/sgl-project/sglang/issues/28528): Kimi-K2.6 NVFP4 + DFLASH + prefix cache; это другой draft/quantization путь, переносить вывод на EAGLE3 нельзя. [vLLM #51660](https://github.com/vllm-project/vllm/issues/51660): EAGLE3/structured-output regression v0.26.0. [Kimi #46](https://github.com/MoonshotAI/Kimi-K2.5/issues/46): сообщения о циклических ответах Kimi-K2.6.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
