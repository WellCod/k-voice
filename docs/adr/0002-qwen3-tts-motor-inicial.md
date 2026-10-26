# ADR-0002 — Qwen3-TTS como motor inicial, atrás de uma interface de motor

- Estado: proposto (vira aceito se passar no teste cego da Fase 0)
- Data: 2026-10-26

## Contexto

Requisitos do modelo: licença comercial nos pesos, pt-BR, streaming de saída com texto incremental, clonagem, controle de estilo/emoção e TTFA comparável à ElevenLabs Flash (~185 ms de mediana no placar da Coval, set/2026).

Candidatos e situação em out/2026 (detalhes em `docs/modelos.md`):

| Modelo | Licença | pt-BR | Streaming | Situação |
|---|---|---|---|---|
| Qwen3-TTS 0.6B/1.7B | Apache-2.0 | sim | sim | principal |
| Chatterbox Multilingual + finetune pt-BR | MIT, com marca d'água Perth | sim | não oficial | comparação |
| Kokoro-82M | Apache-2.0 | sim | sim | piso de latência, sem clonagem |
| Voxtral TTS, Fish S2, XTTS-v2, F5-TTS, OmniVoice | não comercial | — | — | descartados |
| CosyVoice 3 | Apache-2.0 | não | sim | descartado |

## Decisão

Qwen3-TTS como motor inicial. Todo o resto do sistema fala com a interface `TTSEngine` (`docs/arquitetura.md`), nunca com o modelo direto. Trocar de modelo é escrever uma implementação nova e rodar o teste cego de novo.

## Consequências

- O primeiro trabalho é validar o modelo (Fase 0), não construir o serviço.
- A área de modelos abertos muda a cada poucos meses; a interface permite trocar sem refazer o serviço.
- Antes de cada troca de modelo ou versão, conferir licença dos pesos no model card e registrar em `docs/modelos.md`.
