# ADR-0004 — Operação híbrida com a ElevenLabs como fallback até o desligamento

- Estado: aceito
- Data: 2026-10-26

## Contexto

Trocar 100% do tráfego de uma vez arrisca o produto. GPU própria pode cair ou saturar no pico.

## Decisão

- Roteamento por cliente/agente: `kvoice`, `elevenlabs` ou `percentual`.
- Fallback em duas camadas: no plugin do LiveKit (k-voice falhou ou recusou → ElevenLabs) e no servidor (controle de admissão recusa antes de atrasar).
- Rampa: 1% → 10% → 50% → 100%, avançando só com as métricas dentro da meta por 7 dias em cada degrau.
- A ElevenLabs é desligada pelo critério de `docs/escopo.md` (30 dias a 100% dentro das metas). Depois disso, plano mínimo ou desligamento total, com fallback para um segundo grupo de nós k-voice em outra região ou provedor.

## Consequências

- Durante a transição pagamos os dois, mas a conta da ElevenLabs cai na proporção do tráfego desviado.
- Cada voz k-voice precisa de uma voz ElevenLabs "par" para o fallback não trocar a voz no meio da ligação de forma gritante.
