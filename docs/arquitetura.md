# Arquitetura

## Visão geral

```
                       ┌──────────────────────── LiveKit (já existe) ───────────────────────┐
 Telefone ── SIP ──▶   │ LiveKit SIP ─▶ Agent (STT ─▶ LLM ─▶ TTS plugin) ─▶ áudio de volta  │
                       └───────────────────────────────────────┬────────────────────────────┘
                                                               │ WebSocket (texto ▶ / ◀ PCM)
                                                               ▼
 WhatsApp / backends ── HTTP ──▶ ┌──────────── k-voice API (FastAPI) ────────────┐
 Agentes de IA ──────── MCP ───▶ │ auth · roteador · normalizador pt-BR · medição │──▶ Postgres
                                 │ /v1 próprio · /compat/elevenlabs · /mcp        │──▶ S3 (lote, referências)
                                 └──────────────┬───────────────────┬─────────────┘
                                                │                   │ fallback
                                                ▼                   ▼
                                   Engine workers (GPU)        ElevenLabs API
                                   Qwen3-TTS (+ outros)
```

O plugin do LiveKit tenta o k-voice e cai para a ElevenLabs, nessa ordem. O próprio k-voice também pode desviar para a ElevenLabs (roteamento por cliente e fallback do lado servidor), então quem chama pela API HTTP também ganha o fallback.

## Componentes

### 1. `kvoice-api` (Python, FastAPI)
- Autenticação por token de cliente (hash no banco, escopos `tts:stream`, `tts:batch`, `voices:read`, `voices:write`, `admin`).
- Roteador: decide motor por cliente/agente (`kvoice`, `elevenlabs`, `percentual`) e aplica fallback.
- Normalizador pt-BR antes de qualquer motor, inclusive a ElevenLabs (mantém pronúncia igual entre os dois).
- Medição: uma linha por fala em `usage_event`.
- Rotas: `/v1/...` (contrato próprio), `/compat/elevenlabs/v1/...` (subconjunto da API da ElevenLabs), `/mcp` (Streamable HTTP), `/health`, `/metrics`.

### 2. Engine workers (GPU)
- Um processo por GPU, carregando o modelo uma vez e mantendo-o aquecido.
- Interface única para qualquer motor:

```python
class TTSEngine(Protocol):
    name: str
    sample_rate: int

    async def stream(
        self, text: AsyncIterator[str], voice: Voice, opts: SynthOptions
    ) -> AsyncIterator[AudioChunk]: ...

    async def synthesize(self, text: str, voice: Voice, opts: SynthOptions) -> Audio: ...

    def capacity(self) -> Capacity: ...  # streams ativos, fila, RTF recente
```

- Implementações: `QwenTTSEngine` (principal), `ChatterboxEngine` (opcional, avaliação), `ElevenLabsEngine` (proxy HTTP/WebSocket, usado no fallback e na comparação).
- Batching contínuo entre streams concorrentes na mesma GPU. É isso que define quantas ligações cabem por GPU; medir antes de escolher a técnica (CUDA graphs, vLLM ou o runtime do próprio modelo, o que a doc do modelo suportar na versão usada).
- Controle de admissão: se a fila projetar TTFA acima do orçamento, recusa na hora com `503 capacity` para o roteador cair na ElevenLabs em vez de atrasar a fala.

### 3. Normalizador pt-BR (`kvoice.normalize`)
- Puro Python, determinístico, sem rede. Regras + dicionário por cliente.
- Recebe texto incremental: só normaliza até o último limite seguro (fim de palavra/número), segurando o resto até chegar mais texto. Sem isso, "R$ 1.2" seria lido antes de virar "R$ 1.234,50".
- Testado por tabela (`tests/normalize/casos.yaml`).

### 4. Plugin LiveKit (`livekit-plugins-kvoice`)
- Implementa a classe de TTS do LiveKit Agents com streaming (texto incremental de entrada, áudio incremental de saída) e cancelamento.
- Usa o adaptador de fallback do LiveKit Agents com a ElevenLabs como segunda opção, se existir na versão em uso; senão, implementa o fallback no plugin.
- Linguagem do plugin = linguagem do agente atual (Python ou Node). Ver [questões abertas](questoes-abertas.md).

### 5. Armazenamento
- Postgres: `client`, `api_token`, `voice`, `voice_consent`, `pronunciation_entry`, `routing_rule`, `usage_event`, `batch_job`.
- S3 (ou compatível): `references/` (áudio de clonagem, cifrado com SSE-KMS), `outputs/` (lote, com lifecycle de expiração).
- Sem Redis no início. Entra só se o roteamento entre várias réplicas precisar de estado compartilhado.

## Contratos

### Streaming — `WS /v1/tts/stream`

Cliente → servidor (JSON, texto):
```json
{"type": "start", "voice_id": "v_ana", "format": "pcm_24000", "options": {"speed": 1.0, "style": "neutro"}}
{"type": "text", "text": "Oi, tudo bem? Aqui é a Ana, "}
{"type": "text", "text": "da clínica.", "flush": true}
{"type": "cancel"}
{"type": "end"}
```

Servidor → cliente:
- binário: PCM 16-bit little-endian mono no `format` pedido, em pedaços de 20–40 ms;
- JSON: `{"type":"started","request_id":"...","engine":"kvoice","sample_rate":24000}`, `{"type":"flushed"}`, `{"type":"done","ttfa_ms":142,"audio_ms":2380}`, `{"type":"error","code":"capacity"}`.

`flush` força gerar o que já chegou (fim de frase do LLM). `cancel` interrompe e descarta o que está na fila (barge-in). Formatos: `pcm_24000` (padrão LiveKit), `pcm_16000`, `pcm_48000`, `ulaw_8000`.

### Lote — `POST /v1/tts`

```json
{"text": "...", "voice_id": "v_ana", "format": "ogg_opus", "delivery": "url", "url_ttl_s": 86400}
```
Resposta: `{"request_id": "...", "url": "https://...", "duration_ms": 5120, "characters": 312}`. Com `delivery: "bytes"`, devolve o áudio no corpo. Formatos: `ogg_opus` (48 kHz mono, mensagem de voz do WhatsApp), `mp3_44100`, `wav_24000`.

### Compatibilidade ElevenLabs — `/compat/elevenlabs/v1/...`
Só o que o inventário de [paridade-elevenlabs.md](paridade-elevenlabs.md) marcar como usado. `voice_id` da ElevenLabs mapeado para voz k-voice por tabela. Parâmetros sem equivalente são aceitos e ignorados, com log.

### MCP — `/mcp`
Tools: `synthesize(text, voice_id, format) → {url, duration_ms}`, `list_voices(filtros) → [voice]`, `get_voice(voice_id)`. Autenticação pelo mesmo token de cliente. Sem streaming de áudio ([ADR-0006](adr/0006-mcp-so-para-lote.md)).

## Implantação

- Imagem Docker com CUDA, versão de modelo fixada por hash.
- Um nó GPU = `kvoice-api` + 1 engine worker no mesmo pod/VM no início (menos rede no caminho crítico). Separar só se a medição mostrar ganho.
- Balanceador na frente com afinidade por conexão WebSocket e escolha pelo nó com menos streams ativos (o `/health` expõe a capacidade).
- Mínimo de 2 nós GPU; escala por pico de concorrência medido ([operacao.md](operacao.md)).
- Região na mesma nuvem/região do LiveKit para não somar latência de rede.

## Decisões

Ver [docs/adr](adr/).
