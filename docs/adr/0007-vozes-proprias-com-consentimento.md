# ADR-0007 — Vozes próprias de locutores contratados, sempre com consentimento registrado

- Estado: proposto
- Data: 2026-10-26

## Contexto

Variedade e qualidade de voz são requisito. Clonar voz de terceiros sem autorização é risco jurídico (a LGPD trata dado biométrico como sensível) e de reputação. Vozes da biblioteca da ElevenLabs não podem ser levadas para o k-voice.

## Decisão

- Toda voz clonada ou ajustada exige registro em `voice_consent`: quem, contrato, escopo de uso, validade, arquivo do termo.
- Fase 4: contratar 3–5 locutores brasileiros (gêneros, idades e sotaques variados), gravar fala conversacional (não leitura) e fazer ajuste fino do modelo escolhido.
- Até a Fase 4, usar vozes preset do modelo e clones só de pessoas com termo assinado.

## Consequências

- Custo de gravação e contrato entra no orçamento.
- O catálogo de vozes fica nosso, independente de fornecedor.
