# Validação do streaming em GPU na nuvem

Roteiro para medir o `FasterQwen3Engine` numa GPU NVIDIA alugada por hora. Mede duas coisas:

1. **Motor isolado**: streaming contra frase inteira, no mesmo modelo e na mesma GPU (`bench/streaming_gpu.py`).
2. **Servidor completo**: TTFA e cancelamento pelo WebSocket com concorrência (`bench/carga_ws.py`). Esse é o gate da Fase 1: TTFA p95 ≤ 350 ms, cancelamento < 50 ms.

Custo de referência: 1 a 2 horas de máquina. Desligue a instância no fim (passo 8).

## 1. Escolher a máquina

| Requisito | Por quê |
|---|---|
| GPU NVIDIA Ampere ou mais nova (L4, A10, A5000, RTX 4090, L40S) | `faster-qwen3-tts` usa CUDA graphs. O README dele publica números de RTX 4090, H100 e T4; a T4 (Turing) ficou bem mais lenta, ~900 ms de TTFA. |
| 16 GB de VRAM ou mais | 0.6B CustomVoice e o modelo de frase inteira ficam carregados juntos no bench. |
| Driver NVIDIA com suporte a CUDA 13 (`nvidia-smi` mostrando "CUDA Version: 13.x") | O torch fixado no `uv.lock` (2.14.1) traz as bibliotecas `cu13` no Linux. Conferir no passo 2. |
| Ubuntu 22.04 ou 24.04, 40 GB de disco, acesso SSH | Pesos dos dois modelos 0.6B, venv com torch e bibliotecas CUDA, imagem do Postgres. |
| Docker, se for rodar o passo 6 | Postgres do compose. |

Qualquer provedor com SSH serve (RunPod, Lambda, Vast.ai, Google Cloud, AWS). Para o passo 6 contar como medição de produção, use a mesma região do LiveKit.

## 2. Conferir o driver

```bash
nvidia-smi
```

A linha do topo precisa mostrar `CUDA Version: 13.0` ou maior. Se mostrar 12.x, troque de imagem ou de máquina: o torch do lock não vai enxergar a GPU.

## 3. Preparar o código

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
git clone https://github.com/WellCod/k-voice.git
cd k-voice
git switch feat/faster-qwen3-streaming
uv sync --group bench
```

O repositório é privado: autentique antes com `gh auth login` ou copie a pasta com `scp`/`rsync`.

## 4. Conferir o torch

```bash
uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name())"
```

Esperado: `cuda.is_available()` igual a `True` e o nome da GPU. `False` aqui é problema de driver (volte ao passo 2).

## 5. Motor isolado: streaming contra frase inteira

```bash
uv run --group bench python -m bench.streaming_gpu
```

Na primeira execução baixa os pesos do Hugging Face. Para um teste rápido, use `--limite 5 --repeticoes 1`.

Saída: tabela com TTFA p50/p95 e RTF por configuração, e um `bench/outputs/streaming_gpu_*.jsonl` com GPU, driver, versões e data.

- `streaming_c4`, `streaming_c8`, `streaming_c12`: `FasterQwen3Engine` com cada `chunk_size`. Menor dá primeiro som mais cedo e mais custo de decodificação. O valor escolhido vai para `QWEN3_CHUNK_SIZE`.
- `frase_inteira`: o mesmo modelo pelo `qwen_tts`, que só devolve a frase pronta. É a linha de base.

O que olhar: TTFA do streaming bem abaixo do da frase inteira, e RTF menor que 1 (gera mais rápido do que fala).

## 6. Servidor completo pelo WebSocket

```bash
docker compose -f docker-compose.yml up -d postgres
cp .env.example .env
uv run alembic upgrade head
uv run python scripts/criar_admin.py
```

Guarde o token impresso. Em outro terminal, suba o servidor com o motor em GPU:

```bash
QWEN3_ENABLED=true QWEN3_DEVICE=cuda QWEN3_CHUNK_SIZE=8 uv run uvicorn kvoice.api.app:app --host 0.0.0.0 --port 8000
```

No log deve aparecer `Qwen3-TTS carregado (FasterQwen3Engine, ...)`. Se aparecer `Falha ao carregar Qwen3-TTS; usando engine stub`, o erro está logo acima. Medir:

```bash
uv run --group bench python -m bench.carga_ws --url ws://localhost:8000 --token TOKEN --voz v_vivian --concorrencias 1,2,4,8
```

O motor serializa as gerações por modelo, então com concorrência o TTFA cresce com a fila. O resultado mostra quantas chamadas simultâneas cabem por GPU dentro do gate. Acima de 8 na fila, o servidor recusa ou cai para o fallback.

## 7. Trazer os resultados

```bash
scp 'USUARIO@IP:~/k-voice/bench/outputs/*.jsonl' bench/outputs/
```

Com os `.jsonl` no repositório local, os números entram em `docs/resultados/` e em `docs/modelos.md`, com GPU, driver, versões e data, como pede o CLAUDE.md.

## 8. Desligar

Pare ou destrua a instância no painel do provedor. Máquina parada com disco ainda pode cobrar armazenamento.
