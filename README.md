# k-voice

Servidor de síntese de voz (TTS) construído para substituir a ElevenLabs no agente de voz (LiveKit/SIP) e no áudio de WhatsApp. Roda modelos abertos localmente, entrega PCM em tempo real via WebSocket e gera áudio em lote para mensagens de voz.

## Estado atual

**Fases 0–3 concluídas. Fase 4 em andamento (PR 18 entregue).**

| Fase | Descrição | Status |
|---|---|---|
| 0 — Validação | Benchmark offline, teste cego ABX/MOS, latência em GPU | ✅ |
| 1 — Motor e streaming | Engine Qwen3-TTS, normalização pt-BR, API REST, WebSocket | ✅ |
| 2 — LiveKit | Plugin TTS com streaming, cancelamento e fallback | ✅ |
| 3 — Lote, MCP, ElevenLabs | S3, servidor MCP, compat ElevenLabs, dicionário de pronúncia | ✅ |
| 4 — Vozes próprias | Clonagem com consentimento, ajuste fino | 🔄 PR 18 entregue |

## O que está funcionando

| Recurso | Descrição |
|---|---|
| **Streaming WebSocket** | Texto incremental → PCM 16-bit 24 kHz; TTFA < 200 ms (GPU); cancelamento < 50 ms |
| **Síntese em lote** | POST → OGG/Opus gravado em S3, URL assinada com TTL configurável |
| **Normalização pt-BR** | Moeda, datas, CPF/CNPJ, telefones, siglas, CEP — determinístico |
| **Catálogo de vozes** | Vozes preset (Qwen3 CustomVoice) e clonadas (Qwen3 Base) |
| **Clonagem de voz** | Upload de áudio de referência + consentimento LGPD registrado em `voice_consent` |
| **Dicionário de pronúncia** | Por cliente ou global; termos literais e regex |
| **Roteamento** | Por cliente: k-voice puro, fallback ElevenLabs ou proporção configurável |
| **Compatibilidade ElevenLabs** | `POST /v1/text-to-speech/{voice_id}` — troca é só URL base e chave |
| **Servidor MCP** | `synthesize`, `list_voices`, `get_voice` para agentes de IA |
| **Plugin LiveKit** | Interface TTSEngine com streaming e fallback automático |
| **Painel demo** | `GET /demo` — criar vozes, clonar com microfone ou arquivo, testar síntese |

## Rodando em modo CPU (desenvolvimento)

```bash
cp .env.example .env          # ajuste DATABASE_URL e credenciais S3/MinIO
uv run alembic upgrade head
uv run uvicorn kvoice.api.app:app --host 0.0.0.0 --port 8003
```

Acesse `http://localhost:8003/demo`. O motor em CPU usa o `StubEngine` (áudio silencioso) ou o Qwen3-TTS com `device_map=cpu` (lento — primeira síntese de clonagem pode levar 2–5 min).

### Compose de desenvolvimento

```bash
docker compose up -d          # Postgres + MinIO
```

## Rodando com GPU

```bash
docker compose -f compose.gpu.yml up
```

Requer NVIDIA Container Toolkit. TTFA p50 ~156 ms numa RTX 4090.

## Arquitetura

```
                       ┌──────────── LiveKit ──────────────┐
 Telefone ── SIP ──▶   │ Agent (STT ─▶ LLM ─▶ TTS plugin)  │
                       └────────────────┬───────────────────┘
                                        │ WebSocket
                                        ▼
 HTTP clients ──────▶  ┌──────── k-voice API (FastAPI) ────────────────┐
 Agentes via MCP ────▶ │  auth · roteador · normalização pt-BR          │──▶ Postgres
 ElevenLabs compat ──▶ │  /tts · /admin · /v1 · /mcp · /demo           │──▶ S3 / MinIO
                        └──────────────────┬────────────────────────────┘
                                           ▼
                                  Engine workers
                                  Qwen3-TTS 0.6B / 1.7B (GPU/CPU)
                                  StubEngine (testes)
```

**Motor principal: Qwen3-TTS (Apache-2.0)** — streaming nativo, clonagem com ~3 s de referência, suporte a pt-BR.

Toda a stack fala com a interface `TTSEngine`; trocar de modelo é escrever uma implementação nova.

## Modelos avaliados

| Modelo | Licença | pt-BR | Streaming | Situação |
|---|---|---|---|---|
| Qwen3-TTS 0.6B / 1.7B | Apache-2.0 | sim | sim | **principal** |
| Chatterbox Multilingual + finetune pt-BR | MIT | sim | não oficial | comparação |
| Kokoro-82M | Apache-2.0 | sim | sim | piso de latência |
| Voxtral, Fish S2, XTTS-v2, F5-TTS | não comercial | — | — | descartados |

## Metas de desempenho

| Métrica | Meta | Estado |
|---|---|---|
| TTFA p50 / p95 (GPU) | ≤ 200 ms / ≤ 350 ms | medido em `bench/` |
| RTF sob carga | < 0,5 | medido em `bench/` |
| Cancelamento (barge-in) | < 50 ms | implementado |

## Stack

`Python 3.12` · `FastAPI` · `PyTorch + CUDA` · `Qwen3-TTS` · `PostgreSQL` · `SQLAlchemy 2 + Alembic` · `S3 / MinIO` · `LiveKit Agents` · `SDK MCP` · `Docker` · `uv` · `mypy strict` · `ruff` · `pytest`

## Documentos

| | |
|---|---|
| [docs/escopo.md](docs/escopo.md) | Requisitos e critério de sucesso |
| [docs/arquitetura.md](docs/arquitetura.md) | Componentes, contratos de API e formatos de áudio |
| [docs/roadmap.md](docs/roadmap.md) | Fases e PRs na sequência |
| [docs/modelos.md](docs/modelos.md) | Modelos avaliados, licenças e decisões |
| [docs/operacao.md](docs/operacao.md) | SLOs, métricas e capacidade |
| [docs/teste-cego.md](docs/teste-cego.md) | Metodologia do gate de qualidade |
| [docs/adr/](docs/adr/) | Decisões de arquitetura (ADRs) |
