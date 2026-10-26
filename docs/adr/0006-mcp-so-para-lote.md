# ADR-0006 — MCP só para lote; streaming por WebSocket

- Estado: aceito
- Data: 2026-10-26

## Contexto

Uma chamada de tool MCP devolve um resultado; não é um canal de áudio em tempo real. Ligação precisa de áudio contínuo com latência baixa e cancelamento.

## Decisão

- MCP (Streamable HTTP, autenticado por token) com `synthesize`, `list_voices` e `get_voice`. `synthesize` grava no bucket e devolve URL.
- Streaming de ligação só pelo WebSocket `/v1/tts/stream`, usado pelo plugin do LiveKit.

## Consequências

- Agentes de IA (inclusive o automata, que já cadastra servidores MCP externos) pedem áudio para WhatsApp pelo MCP.
- Nenhum cliente tenta fazer ligação pelo MCP.
