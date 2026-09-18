# Recipe migration · 2026-09-18

15 базовых рецептов используют опубликованные образы с digest, внутреннюю Docker сеть,
SMG 30001, engine 30000 и общую точку метрик 9234. Env содержит только security inputs
и адрес внешней telemetry. Reasoning, throughput budgets и upstream issues описаны в каждом README.

| Recipe | Cache variants |
|---|---|
| [sglang/deepseek-v4-flash-vision-hgx-h200](../../sglang/deepseek-v4-flash-vision-hgx-h200/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-hicache](../../sglang/glm-5.1-nvfp4-hicache/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-mooncake-b200](../../sglang/glm-5.1-nvfp4-mooncake-b200/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-mooncake-host](../../sglang/glm-5.1-nvfp4-mooncake-host/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-mooncake-separate](../../sglang/glm-5.1-nvfp4-mooncake-separate/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-mooncake-separate-small](../../sglang/glm-5.1-nvfp4-mooncake-separate-small/README.md) | base / RAM / RAM+SSD |
| [sglang/glm-5.1-nvfp4-smg](../../sglang/glm-5.1-nvfp4-smg/README.md) | base / RAM / RAM+SSD |
| [sglang/kimi-k2.6-eagle3-hicache](../../sglang/kimi-k2.6-eagle3-hicache/README.md) | base / RAM / RAM+SSD |
| [sglang/qwen3-8b-dpa](../../sglang/qwen3-8b-dpa/README.md) | base / RAM / RAM+SSD |
| [vllm/deepseek-v4-flash-vision-hgx-h200-lmcache](../../vllm/deepseek-v4-flash-vision-hgx-h200-lmcache/README.md) | base; RAM/SSD blocked |
| [vllm/diffusiongemma-26b-a4b-int8-tiered-kv](../../vllm/diffusiongemma-26b-a4b-int8-tiered-kv/README.md) | base / RAM / RAM+SSD |
| [vllm/gemma4-26b-a4b-tiered-kv](../../vllm/gemma4-26b-a4b-tiered-kv/README.md) | base / RAM / RAM+SSD |
| [vllm/kimi-k2.6-dep8-eagle3](../../vllm/kimi-k2.6-dep8-eagle3/README.md) | base / RAM / RAM+SSD |
| [vllm/kimi-k2.6-tp8](../../vllm/kimi-k2.6-tp8/README.md) | base / RAM / RAM+SSD |
| [sglang/qwen3.8-27b-fp8-hicache](../../sglang/qwen3.8-27b-fp8-hicache/README.md) | base / RAM / RAM+SSD |

14 рецептов имеют два независимых cache overlay. DeepSeek Vision/vLLM LMCache заблокирован до проверки опубликованного совместимого образа или отдельного решения о сборке.

Изменения runtime: SGLang (кроме Vision) 0.5.19; vLLM Kimi 0.26.0;
Qwen3.8 gRPC заменён штатным HTTP, default effort medium;
Gemma/DiffusionGemma thinking включён; GLM speculation отключена из-за HiCache issues;
vLLM Kimi EAGLE3 отключён из-за structured-output regression.

Статические проверки не подтверждают GPU работоспособность. Target-host admission включает hardware,
модель, RAM и SSD capacity; acceptance дополнительно проверяет reasoning, tool/vision, prefix reuse,
SSD restore, pressure/cancel и aggregate throughput. Сборки и GPU deployment не выполнялись.
