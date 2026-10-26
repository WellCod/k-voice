# Paridade com a ElevenLabs

Inventário do que o produto usa da ElevenLabs hoje e como cada item fica no k-voice. **Preencher a coluna "Usamos?" antes da Fase 3**, a partir do código das integrações e da fatura. O que não for usado não é implementado.

Os nomes de endpoint e parâmetro precisam ser conferidos na doc oficial da ElevenLabs na hora de implementar.

## Síntese

| Recurso ElevenLabs | Usamos? | Onde | Como fica no k-voice | Fase |
|---|---|---|---|---|
| Plugin do LiveKit Agents (TTS streaming) | sim | agente de voz | plugin `livekit-plugins-kvoice` | 2 |
| WebSocket de entrada em streaming (texto incremental) | ? | | `WS /v1/tts/stream` | 1 |
| HTTP text-to-speech (arquivo inteiro) | ? | WhatsApp? | `POST /v1/tts` e compat | 3 |
| HTTP text-to-speech com streaming de resposta | ? | | compat | 3 |
| Modelo usado (Flash, Turbo, Multilingual, v3) | ? | | motor k-voice | 0 |
| Formatos de saída (pcm_*, ulaw_8000, mp3_*, opus) | ? | | ver `arquitetura.md` | 1/3 |
| Ajustes de voz (stability, similarity, style, speed) | ? | | `options` próprias; compat aceita e mapeia o que der | 1/3 |
| Tags de emoção ou áudio (modelo v3) | ? | | instrução de estilo do motor, se suportado | 4 |
| Dicionário de pronúncia | ? | | dicionário por cliente | 3 |
| Normalização de texto da ElevenLabs | ? | | normalizador pt-BR próprio | 1 |
| Timestamps por caractere ou palavra (alignment) | ? | legenda, sincronismo? | avaliar se o modelo dá; senão alinhamento forçado | — |

## Vozes

| Recurso | Usamos? | Como fica |
|---|---|---|
| Vozes da biblioteca | ? | não migram; substituir por preset do modelo e depois por vozes próprias (ADR-0007) |
| Instant Voice Clone | ? | clonagem com consentimento (Fase 4) |
| Professional Voice Clone | ? | ajuste fino com locutor contratado (Fase 4) |
| Voice Design (voz por descrição) | ? | VoiceDesign do Qwen3-TTS, se aprovado |

## Fora do escopo do k-voice (registrar se usamos)

| Recurso | Usamos? | Destino |
|---|---|---|
| Speech-to-text (Scribe) | ? | fica com o provedor de STT do LiveKit |
| Conversational AI / Agents da ElevenLabs | ? | não: a orquestração é o LiveKit |
| Speech-to-speech, dublagem, efeitos, isolamento de voz | ? | fora |

## Números a coletar (entram em `custos.md`)

- Caracteres por mês (últimos 3 meses), separados por ligação e lote.
- Minutos de ligação por mês.
- Pico de ligações simultâneas e o horário dele.
- Plano e preço por caractere atual.
