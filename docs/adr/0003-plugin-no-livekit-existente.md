# ADR-0003 — Plugin no LiveKit existente, sem orquestração própria

- Estado: aceito
- Data: 2026-10-26

## Contexto

O agente de voz já roda no LiveKit (Agents + SIP), que cuida de STT, LLM, VAD, turnos, interrupção e telefonia. A ElevenLabs entra hoje como plugin de TTS.

## Decisão

O k-voice é só o TTS. Entra no agente como um plugin de TTS do LiveKit Agents, com streaming de texto de entrada e de áudio de saída e suporte a cancelamento.

## Consequências

- O escopo cai de "plataforma de agente de voz" para "servidor de voz + plugin".
- O plugin precisa seguir a versão do LiveKit Agents em uso; a interface de TTS muda entre versões, então confirmar na doc da versão antes de implementar.
- Ganhos de naturalidade que dependem de turnos e interrupção continuam sendo ajustados no agente, fora deste repositório.
