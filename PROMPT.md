# Prompt inicial para o agente

Cole o bloco abaixo numa sessão nova do agente (Claude Code ou outro), aberta na pasta do projeto.

---

Você vai implementar o **k-voice**, um servidor de voz próprio (texto → fala) que substitui a ElevenLabs no nosso agente de voz telefônico (LiveKit) e no áudio enviado por WhatsApp. O requisito é voz super realista em pt-BR, com latência equivalente à da ElevenLabs, a um custo menor que os ~US$ 5 mil/mês atuais. No sucesso, a ElevenLabs é desligada.

**Antes de escrever qualquer código:**

1. Leia `CLAUDE.md`, `README.md` e todos os arquivos de `docs/`, incluindo os ADRs. Eles são a fonte de verdade de escopo, arquitetura, fases e regras de trabalho.
2. Abra `docs/questoes-abertas.md` e me pergunte as questões marcadas "antes da Fase 0", de uma vez, numa lista curta. Não suponha respostas.
3. Confirme na doc oficial, nas versões atuais: a API de streaming do Qwen3-TTS, a licença dos pesos do Qwen3-TTS e do Chatterbox pt-BR, e a interface de TTS do LiveKit Agents na versão que eu informar. Me diga se algo contradiz o que está em `docs/` (por exemplo: licença mudou, modelo novo melhor surgiu, API diferente). Se contradizer um ADR, proponha a mudança antes de seguir.

**Depois, comece pela Fase 0 de `docs/roadmap.md`, PR 1.** Siga o protocolo de `CLAUDE.md`: um PR por vez, draft até verde, `gh pr ready` quando completo, e espere meu "prossiga" para o próximo, a não ser que eu autorize a sequência inteira.

**Princípios:**

- A Fase 0 decide se o projeto existe. Não construa o serviço antes do gate do teste cego (`docs/teste-cego.md`). Se nenhum modelo passar, o resultado certo é dizer isso com os números e parar.
- Meça tudo que afirmar sobre latência, capacidade e qualidade, com hardware, versão e data. Número de fabricante é só referência.
- O sistema inteiro fala com a interface `TTSEngine` (`docs/arquitetura.md`). Nenhum código fora de `kvoice/engines/` conhece o modelo.
- A ElevenLabs continua como fallback até o critério de desligamento de `docs/escopo.md`. Nunca remova o fallback antes disso.
- Modelo com pesos não comerciais está fora, sem exceção. Clonagem só com consentimento registrado. Não remova marca d'água.
- Quando precisar de GPU para benchmark, me diga qual, por quanto tempo e o custo estimado antes de eu provisionar.

Ao terminar cada PR, me dê: o que mudou, como verificar, números medidos (se houver) e o que fica para o próximo.
