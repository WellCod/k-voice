# k-voice

Servidor de síntese de voz (TTS) com streaming, construído do zero como projeto de estudo. Roda modelos abertos em GPU, entrega PCM em tempo real via WebSocket para agentes de voz no LiveKit e gera áudio em lote para mensagens de voz.

## O que faz

| Modo | Descrição |
|---|---|
| **Streaming** | WebSocket com texto incremental → PCM 16-bit 24 kHz; primeiro áudio antes do texto terminar; cancelamento em < 50 ms para barge-in |
| **Lote** | HTTP POST → OGG/Opus 48 kHz gravado em S3 com URL assinada |
| **Normalização pt-BR** | Moeda, datas, CPF/CNPJ, telefones, siglas, CEP — determinístico, roda antes de qualquer motor |
| **Catálogo de vozes** | Vozes preset e clonadas a partir de áudio de referência |
| **Plugin LiveKit** | Implementa a interface de TTS do LiveKit Agents com fallback automático |
| **Compatibilidade ElevenLabs** | Subconjunto da API pública — troca é só URL base e chave |
| **MCP** | Servidor Streamable HTTP com `synthesize`, `list_voices`, `get_voice` |

## Arquitetura

```
                       ┌──────────── LiveKit ──────────────┐
 Telefone ── SIP ──▶   │ Agent (STT ─▶ LLM ─▶ TTS plugin)  │
                       └────────────────┬───────────────────┘
                                        │ WebSocket
                                        ▼
 HTTP clients ──────▶  ┌──────── k-voice API (FastAPI) ─────┐
 Agentes via MCP ────▶ │ auth · roteador · normalização pt-BR│──▶ Postgres
                        │ /v1 · /compat/elevenlabs · /mcp    │──▶ S3
                        └──────────────┬─────────────────────┘
                                       ▼
                               Engine workers (GPU)
                               Qwen3-TTS + outros
```

**Motor principal: Qwen3-TTS (Apache-2.0)** — streaming nativo, clonagem com ~3 s de referência, suporte a pt-BR, TTFA ~156 ms numa RTX 4090. Toda a stack fala com a interface `TTSEngine`; trocar de modelo é escrever uma implementação nova.

## Meta de desempenho

| Métrica | Meta |
|---|---|
| TTFA p50 / p95 (servidor) | ≤ 200 ms / ≤ 350 ms |
| RTF sob carga | < 0,5 (gera 2× mais rápido que o tempo real da fala) |
| Cancelamento (barge-in) | < 50 ms |

## Modelos avaliados

| Modelo | Licença | pt-BR | Streaming | Situação |
|---|---|---|---|---|
| Qwen3-TTS 0.6B / 1.7B | Apache-2.0 | sim | sim | **principal** |
| Chatterbox Multilingual + finetune pt-BR | MIT | sim | não oficial | comparação |
| Kokoro-82M | Apache-2.0 | sim | sim | piso de latência |
| Voxtral, Fish S2, XTTS-v2, F5-TTS | não comercial | — | — | descartados |

## Roadmap

```
Fase 0 — Validação     benchmark offline, teste cego ABX/MOS, latência e concorrência em GPU
Fase 1 — Motor         engine com interface unificada, normalização, API, WebSocket, infra CUDA
Fase 2 — LiveKit       plugin TTS com streaming e cancelamento
Fase 3 — Integrações   lote com S3, MCP, compatibilidade ElevenLabs, dicionário de pronúncia
Fase 4 — Vozes         clonagem com consentimento registrado, ajuste fino
```

Estado atual: **Fase 0** — documentação e decisões de arquitetura concluídas, nenhum código ainda.

## Stack

`Python 3.12` · `FastAPI` · `PyTorch + CUDA` · `Qwen3-TTS` · `PostgreSQL` · `SQLAlchemy 2 + Alembic` · `S3` · `LiveKit Agents` · `SDK MCP` · `Docker` · `uv` · `mypy strict` · `ruff` · `pytest`

## Documentos

| | |
|---|---|
| [docs/escopo.md](docs/escopo.md) | Requisitos e critério de sucesso |
| [docs/arquitetura.md](docs/arquitetura.md) | Componentes, contratos de API e formatos de áudio |
| [docs/roadmap.md](docs/roadmap.md) | Fases e PRs na sequência |
| [docs/modelos.md](docs/modelos.md) | Modelos avaliados, licenças e por que cada um entrou ou saiu |
| [docs/operacao.md](docs/operacao.md) | SLOs, métricas e capacidade |
| [docs/teste-cego.md](docs/teste-cego.md) | Metodologia do gate de qualidade |
| [docs/adr/](docs/adr/) | 8 decisões de arquitetura |
