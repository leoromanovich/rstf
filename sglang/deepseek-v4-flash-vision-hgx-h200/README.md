# deepseek-v4-flash-vision-hgx-h200

Модель: `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`. HGX 8×H200; model revision `6821d6ad3681a4b137b066b76094fa82ebd0a380`, context 200000. Preview image закреплён digest. TP8/DP8/DPA/EP1, A2A=none; 256 running total (32/rank), prefill 32768 total (4096/rank), queue 64/rank. HiCache использует ratio 1.25, direct/page_first_direct, page 256; `hicache-size` для V4 запрещён. RAM tier требует около 1.5 TB доступной памяти. SSD лимит 10T/rank не является общей квотой.

Throughput budgets: `tp-size=8, dp-size=8, context-length=200000, max-running-requests=256, chunked-prefill-size=32768`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

Thinking включён явно. Native encoder Vision имеет `low/high/max`; отдельного `medium` нет. Удалён принудительный `high`, применявший maximum-effort instruction. Default закреплённого official encoder — `low` (обычное thinking без усиливающей инструкции). [Модель и reference encoder](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp), [SGLang Vision source](https://github.com/sgl-project/sglang/blob/40b3e15ddbd9a1067e181283d9900dd3f4d76ed7/python/sglang/srt/entrypoints/openai/encoding_dsv4.py).

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
3. Через CC feature override вызови `inference-recipe-control sglang/deepseek-v4-flash-vision-hgx-h200 config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`. Для cache tiers замени `none` на `ram` или `ssd`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверка upstream — 2026-09-18

[LMCache #3957](https://github.com/LMCache/LMCache/issues/3957): несовпадение MP connector API на другом релизе vLLM; совместимость нельзя выводить только из наличия пакета. [HMA design](https://github.com/LMCache/LMCache/blob/dev/docs/design/integration/vllm/hybrid-kv-cache-groups.md): необходимы hybrid groups и совместимый layout.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
