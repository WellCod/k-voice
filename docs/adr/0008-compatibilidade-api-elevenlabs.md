# ADR-0008 — Camada compatível com a parte da API da ElevenLabs que usamos

- Estado: proposto
- Data: 2026-10-26

## Contexto

Além do agente de voz, outros pontos do produto podem chamar a ElevenLabs direto (áudio de WhatsApp, por exemplo). Reescrever cada integração atrasa o desligamento.

## Decisão

Expor `/compat/elevenlabs/v1/...` com só os endpoints e parâmetros listados como usados em `docs/paridade-elevenlabs.md`. `voice_id` da ElevenLabs mapeado para voz k-voice por tabela. Parâmetros sem equivalente são aceitos e registrados em log.

## Consequências

- Migração dessas integrações vira troca de URL base e chave.
- O formato da API da ElevenLabs precisa ser conferido na doc oficial antes de implementar; não reproduzir de memória.
- Quando todas as integrações migrarem para `/v1`, a camada pode ser removida.
