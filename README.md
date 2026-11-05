# k-voice

Servidor de síntese de voz (TTS) próprio para substituir a ElevenLabs em dois usos: o agente de voz que atende ligações (LiveKit/SIP) e as mensagens de áudio do WhatsApp. Roda o Qwen3-TTS, um modelo aberto com licença comercial, e entrega áudio em tempo real por WebSocket ou em lote por URL assinada.

Toda a stack fala com uma interface única de motor (`TTSEngine`). Trocar de modelo é escrever uma implementação nova, sem mexer em API, roteamento ou normalização.

## Estado

O serviço está implementado e testado. A troca da ElevenLabs depende de medições em GPU que ainda não foram feitas. Os números que decidem se o projeto segue (qualidade no teste cego e latência sob carga) são o próximo passo, com roteiro pronto em [docs/gpu-nuvem.md](docs/gpu-nuvem.md).

| Fase | Entregue | Pendente |
|---|---|---|
| 0 — Validação | Benchmarks de síntese, degradação para telefone, página de teste cego ABX/MOS, bench de latência | Rodar o teste cego e registrar o resultado ([PR 5](docs/roadmap.md)) |
| 1 — Motor e streaming | Qwen3-TTS com streaming e cancelamento, normalização pt-BR, banco, WebSocket, imagem CUDA | Gate: TTFA p95 ≤ 350 ms e cancelamento < 50 ms medidos em GPU |
| 2 — LiveKit | Plugin TTS com streaming e fallback, roteamento por cliente, carga SIP simulada | Rampa de 1% a 10% do tráfego real |
| 3 — Lote, MCP e compat | Lote em OGG/Opus, servidor MCP, API compatível com a ElevenLabs, dicionário de pronúncia | Migrar as integrações de WhatsApp |
| 4 — Vozes próprias | Clonagem com consentimento e referência cifrada | Ajuste fino por voz, vozes dos locutores, novo teste cego |
| 5 — Substituição | — | Painéis de SLO, segunda região, rampa a 100% |

Detalhe por PR em [docs/roadmap.md](docs/roadmap.md).

## O que o servidor faz

| Recurso | Como funciona |
|---|---|
| **Streaming** (`WS /v1/tts/stream`) | O texto chega em pedaços, como sai de um LLM. Cada frase completa vai para o motor na hora; em GPU, o `faster-qwen3-tts` envia o primeiro pedaço de áudio antes de terminar a frase. PCM 16-bit 24 kHz, cancelamento imediato (barge-in) e `flushed` alinhado ao fim do áudio de cada trecho. |
| **Lote** (`POST /v1/tts`) | OGG/Opus, MP3 ou WAV, devolvido no corpo ou gravado em S3 com URL assinada e expiração. Textos longos são divididos por frase e unidos com 60 ms de pausa. |
| **Normalização pt-BR** | Determinística e testada por tabela: moeda, datas, horas, CPF/CNPJ, CEP, telefone, ordinais, porcentagem, decimais, siglas soletradas ou lidas como palavra, anglicismos. No streaming, só normaliza até um limite seguro para não ler "R$ 1.2" antes de virar "R$ 1.234,50". |
| **Dicionário de pronúncia** | Global ou por cliente, literal ou regex, aplicado nos quatro caminhos. No streaming vale mesmo com o termo partido entre dois pedaços do LLM. |
| **Vozes** | Preset (speakers do Qwen3 CustomVoice) e clonadas a partir de referência (Qwen3 Base). |
| **Clonagem** | O upload passa por ffmpeg (corte de silêncio, loudnorm, WAV 16 kHz mono) e exige 5 s de fala limpa. Cada referência registra consentimento em `voice_consent` ([ADR-0007](docs/adr/0007-vozes-proprias-com-consentimento.md)) e é gravada cifrada; o motor decifra para um temporário só durante a geração. |
| **Roteamento e fallback** | Por cliente: só k-voice, só ElevenLabs ou percentual. Com a fila do motor cheia, cai para a ElevenLabs em vez de atrasar a fala. |
| **Compatibilidade ElevenLabs** | `POST /v1/text-to-speech/{voice_id}` com `xi-api-key`: integração existente troca só a URL base e a chave ([ADR-0008](docs/adr/0008-compatibilidade-api-elevenlabs.md)). |
| **MCP** | `synthesize`, `list_voices` e `get_voice` em `/mcp` (Streamable HTTP), só lote ([ADR-0006](docs/adr/0006-mcp-so-para-lote.md)). |
| **Plugin LiveKit** | `kvoice.livekit.TTS` com streaming e cancelamento; `create_tts` monta o `FallbackAdapter` com a ElevenLabs. |
| **Medição** | Uma linha por fala em `usage_event` (caracteres, áudio, TTFA, motor, fallback) e métricas Prometheus em `/metrics`. |
| **Painel demo** | `/demo`: criar vozes preset ou clonadas, gravar referência pelo microfone e testar a síntese. |

## Como funciona

```
                       ┌──────────── LiveKit ──────────────┐
 Telefone ── SIP ──▶   │ Agent (STT ─▶ LLM ─▶ TTS plugin)  │
                       └────────────────┬──────────────────┘
                                        │ WebSocket
                                        ▼
 HTTP (lote) ───────▶  ┌──────────── k-voice (FastAPI) ─────────────┐
 Agentes via MCP ───▶  │ auth · roteador · normalização · medição   │──▶ Postgres
 Compat ElevenLabs ─▶  │ /v1/tts · /v1/text-to-speech · /mcp · /demo │──▶ S3 / MinIO
                       └─────────────────────┬──────────────────────┘
                                             ▼
                         FasterQwen3Engine (GPU, streaming na frase)
                         Qwen3TTSEngine    (CPU, frase a frase)
                         ElevenLabsEngine  (fallback)
```

O motor é escolhido por `QWEN3_DEVICE`: `cuda` usa o `faster-qwen3-tts` com CUDA graphs; `cpu` usa o módulo `qwen_tts` e sintetiza frase a frase. Contratos e formatos em [docs/arquitetura.md](docs/arquitetura.md).

## Rodando localmente (CPU)

Requer Python 3.12, [uv](https://docs.astral.sh/uv/), Docker e ffmpeg.

```bash
docker compose up -d                 # Postgres + MinIO
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python scripts/criar_admin.py # imprime o primeiro token de admin
```

Gere a chave do áudio de referência e coloque em `REFERENCE_AUDIO_KEY` no `.env`; sem ela o upload de clonagem é recusado:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Suba o servidor e abra `http://localhost:8003/demo` com o token de admin:

```bash
uv run uvicorn kvoice.api.app:app --port 8003
```

Sem `QWEN3_ENABLED=true` o servidor usa o `StubEngine`, que gera um tom proporcional ao texto, útil para testar a API sem modelo. Com o modelo em CPU, a síntese é lenta: num Ryzen 7 7735HS, 36 s para 3,6 s de áudio (0.6B, float32, medição em [docs/modelos.md](docs/modelos.md)).

## Rodando em GPU

Requer GPU NVIDIA e driver com CUDA 13 (o torch fixado traz as bibliotecas `cu13`).

```bash
docker compose -f docker-compose.dev.yml up --build
```

Sobe Postgres, MinIO, a migração e o servidor na porta 8000 com a GPU reservada. Defina no `.env` `QWEN3_ENABLED=true` e `QWEN3_DEVICE=cuda`. Para medir latência e concorrência numa GPU alugada, siga [docs/gpu-nuvem.md](docs/gpu-nuvem.md).

## Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `DATABASE_URL` | Postgres local | Banco (asyncpg) |
| `S3_*` | MinIO local | Áudio de lote |
| `REFERENCE_AUDIO_KEY` | vazio | Chave Fernet do áudio de referência; só por ambiente |
| `ELEVENLABS_API_KEY` | vazio | Habilita o fallback |
| `QWEN3_ENABLED` | `false` | Carrega o Qwen3-TTS; senão usa o stub |
| `QWEN3_DEVICE` | `cpu` | `cuda` ativa o streaming em GPU |
| `QWEN3_DTYPE` | `auto` | float32 em CPU, bfloat16 em CUDA |
| `QWEN3_CHUNK_SIZE` | `8` | Pedaço do streaming em GPU (~`chunk_size`/12 s de áudio) |
| `QWEN3_MODEL_ID` / `QWEN3_BASE_MODEL_ID` | 0.6B CustomVoice / Base | Modelos preset e de clonagem |
| `QWEN3_SPEAKER` | `vivian` | Speaker padrão das vozes preset |

## Desempenho

| Métrica | Meta | Medido |
|---|---|---|
| TTFA p50 / p95 em GPU | ≤ 200 / ≤ 350 ms | pendente ([docs/gpu-nuvem.md](docs/gpu-nuvem.md)) |
| Cancelamento | < 50 ms | pendente em GPU; em teste, não espera a geração em curso |
| RTF sob carga | < 0,5 | pendente |

Afirmações de latência e qualidade só valem com medição no repositório (`bench/`), com hardware, versão e data. Números de fabricante ficam em [docs/modelos.md](docs/modelos.md), marcados como tal.

## Modelos

| Modelo | Licença dos pesos | pt-BR | Situação |
|---|---|---|---|
| Qwen3-TTS 0.6B / 1.7B | Apache-2.0 | sim | **principal**; instrução de estilo só no 1.7B |
| Chatterbox Multilingual + finetune pt-BR | MIT | sim | comparação |
| Kokoro-82M | Apache-2.0 | sim | piso de latência, sem clonagem |
| Voxtral, Fish S2, XTTS-v2, F5-TTS | não comercial | — | descartados |

Pesos com licença não comercial ficam fora. Versões, compatibilidade e medições em [docs/modelos.md](docs/modelos.md).

## Engenharia

- 176 testes (pytest), integração com Postgres real via testcontainers, mypy strict e ruff no CI.
- Toda mudança na normalização ou no motor roda a tabela de regressão (`tests/normalize/casos.yaml` e `bench/frases.yaml`).
- Decisões em [ADRs](docs/adr/); segredos só por ambiente; tokens de cliente guardados como hash; token do WebSocket ocultado nos logs.

`Python 3.12` · `FastAPI` · `PyTorch + CUDA` · `Qwen3-TTS` · `faster-qwen3-tts` · `PostgreSQL` · `SQLAlchemy 2 + Alembic` · `S3 / MinIO` · `LiveKit Agents` · `MCP` · `Docker` · `uv`

## Documentos

| | |
|---|---|
| [docs/escopo.md](docs/escopo.md) | Requisitos e critério de sucesso |
| [docs/arquitetura.md](docs/arquitetura.md) | Componentes, contratos de API e formatos |
| [docs/roadmap.md](docs/roadmap.md) | Fases, PRs e gates |
| [docs/modelos.md](docs/modelos.md) | Modelos, licenças, versões e medições |
| [docs/operacao.md](docs/operacao.md) | SLOs, métricas, capacidade e plantão |
| [docs/gpu-nuvem.md](docs/gpu-nuvem.md) | Roteiro de validação em GPU alugada |
| [docs/teste-cego.md](docs/teste-cego.md) | Metodologia do gate de qualidade |
| [docs/adr/](docs/adr/) | Decisões de arquitetura |
