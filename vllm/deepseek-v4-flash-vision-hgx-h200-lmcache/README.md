# deepseek-v4-flash-vision-hgx-h200-lmcache

Модель: `DeepSeek-V4-Flash-Vision-Exp`. HGX 8×H200; model revision `6821d6ad3681a4b137b066b76094fa82ebd0a380`, context 400000. Preview image закреплён digest. TP1/DP8/EP8, A2A allgather_reducescatter, Marlin, 32 sequences/rank, batch 8192/rank. База использует исходный готовый Vision image; LMCache в ней отсутствует.

Throughput budgets: `tensor-parallel-size=1, data-parallel-size=8, max-model-len=400000, max-num-seqs=32, max-num-batched-tokens=8192`. Изменение оборудования требует повторной проверки capacity и aggregate tokens/s.

## Reasoning

Thinking включён явно. Native encoder Vision имеет `low/high/max`; отдельного `medium` нет. В kwargs задан `medium`: vLLM tokenizer отображает этот compatibility alias в native `low`. Mapping необходимо подтвердить на закреплённом preview-образе; его source revision не опубликован в labels. [Модель и reference encoder](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp), [SGLang Vision source](https://github.com/sgl-project/sglang/blob/40b3e15ddbd9a1067e181283d9900dd3f4d76ed7/python/sglang/srt/entrypoints/openai/encoding_dsv4.py).

## Cache tiers

База — без offloading.

**BLOCKED: RAM и RAM+SSD для vLLM Vision + LMCache.** Опубликованный `lmcache/vllm-openai:nightly-2026-09-17` найден, но его vLLM/LMCache ABI, Vision и native NHD/HMA совместимость с preview не подтверждены. Cache overlays отсутствуют, controller отклоняет их выбор. Нужен проверенный опубликованный образ либо отдельное решение пользователя о сборке по сохранённому Dockerfile. Наличие nightly не означает готовность к запуску.

## Запуск

API SMG — `127.0.0.1:30001`; engine — `vllm:30000` внутри Docker.
Collector экспортирует метрики движка и SMG на `127.0.0.1:9234/metrics`.
Внутренний OTLP transport — `otel-collector:4317/4318`; локальный Jaeger UI (где включён) — `127.0.0.1:16686`.

1. Проверь bind paths, GPU и cache budgets в Compose; подготовь каталоги и SSD quota.
2. Скопируй `.env.example` в защищённый локальный `.env`; задай API/admin keys и внешний OTLP endpoint, где требуется. Константы в env не выносятся.
3. Через CC feature override вызови `inference-recipe-control vllm/deepseek-v4-flash-vision-hgx-h200-lmcache config --cache none`.
4. На целевом Linux GPU host выполни `preflight --cache none --env-file /secure/recipe.env`.
5. Для согласованного запуска: `RECIPE_CONFIRM=mutate-inference` и действие `up --cache none --env-file /secure/recipe.env`.

Lifecycle/Nix: [общая инструкция](../../misc/telemetry/README.md).
`up` всегда передаёт `--no-build`. Эксперимент: `--experiment` создаёт локальный временный `restart: "no"` override; опубликованный default — `unless-stopped`.

## Проверки на HGX

Budget: до 384000 входных токенов с учётом template/images + 16000 на
reasoning/answer. Контекст 400k задаёт предел одного запроса; конкурентную
ёмкость необходимо измерить по доступному KV и aggregate tokens/s.

```bash
export RECIPE_ROOT=/srv/nyashkimyashki
export VLLM_DSV4_ENV_FILE=/secure/recipe.env
./cc feature compose-recipes-contract run nyashkimyashki-vllm-dsv4-lmcache-h200-control smoke
./cc feature compose-recipes-contract run nyashkimyashki-vllm-dsv4-lmcache-h200-control acceptance --run-id canary-400k --prompt-tokens 384000
```

Probes выполняются внутри работающего vLLM-контейнера через Compose exec;
engine остаётся доступен только внутри Docker. `smoke` проверяет text, SSE,
два последовательных tool round trips в JSON/SSE и red/blue/red images на
ranks 0/1/7. `acceptance` считает полный template через `/tokenize`, проверяет
маркеры в начале/середине/конце и повторяет запрос на ranks 0/0/1/7.
Для ступеней 32k/128k total используй `--prompt-tokens 16000` / `112000`.
Stdout содержит метрики и результаты проверок; prompts/answers не сохраняются.
Эти probes явно отключают thinking для воспроизводимой проверки; default
reasoning сервера проверяется отдельным запросом без template kwargs.

Default stage `base` проверяет correctness/TTFT без LMCache. Сохранённые
`warm`, `ram-restore`, `ssd-restore` требуют отдельного совместимого cache
стека и явного `--metrics-url`; в текущем рецепте offloading заблокирован.
Они проверяют прирост MP load counters на выделенном инстансе. Три маркера
дают ограниченную text-проверку; tools/images и throughput на длинных
контекстах требуют отдельного прогона.

## Проверка upstream — 2026-09-18

[LMCache #3957](https://github.com/LMCache/LMCache/issues/3957): несовпадение MP connector API на другом релизе vLLM; совместимость нельзя выводить только из наличия пакета. [HMA design](https://github.com/LMCache/LMCache/blob/dev/docs/design/integration/vllm/hybrid-kv-cache-groups.md): необходимы hybrid groups и совместимый layout.

Выбор версий основан на source и опубликованных registry manifests. Проверены schema/merge/argv всех доступных tiers; GPU smoke, reasoning output, tool/vision, throughput и cache restore в этой миграции не запускались. На целевом host проверь запрос без reasoning-параметров, холодный/тёплый prefix cache и повторный запуск SSD tier; сравни correctness и aggregate tokens/s.
