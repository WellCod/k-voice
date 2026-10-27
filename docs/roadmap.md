# Roadmap

Cada fase termina num gate. Não começar a fase seguinte sem o gate cumprido e aprovado pelo usuário.

Numeração dos PRs é a ordem planejada; no GitHub vale o número real.

## Fase 0 — Validação (gate de existência do projeto)

Pergunta: algum modelo aberto, com licença comercial, empata com a ElevenLabs em áudio de telefone pt-BR e aguenta a concorrência com latência na meta?

- [x] PR 1 — `chore: scaffolding do projeto python`
  `git init` próprio na pasta (ela está dentro de `Documents`, que já é um repositório git), uv, Python 3.12, ruff, mypy strict, pytest, CI (lint, tipos, testes), estrutura `src/kvoice`, `bench/`, `docs/`.
- [x] PR 2 — `feat(bench): síntese offline com qwen3-tts, chatterbox pt-br, kokoro e elevenlabs`
  Script que gera o mesmo conjunto de frases (`bench/frases.yaml`, ver [teste-cego.md](teste-cego.md)) em cada motor, com vozes equivalentes, e grava WAV + metadados.
- [x] PR 3 — `feat(bench): áudio de telefone e página do teste cego`
  Degradação para 8 kHz μ-law (e Opus de WebRTC), página HTML estática com teste ABX e nota MOS, exportação das respostas em CSV, análise estatística.
- [x] PR 4 — `feat(bench): latência e concorrência em gpu`
  TTFA p50/p95 e RTF com 1, 4, 8, 16, 32 streams simultâneos, texto chegando em pedaços como sai de um LLM. Mesmo teste contra a ElevenLabs a partir da mesma região.
- [ ] PR 5 — `docs: resultado da fase 0`
  Números, áudios de exemplo, decisão. ADR-0002 vira aceito ou o projeto para ([escopo.md](escopo.md), critério de parada).

Gate: critérios de [teste-cego.md](teste-cego.md) atendidos.

## Fase 1 — Motor e streaming

- [x] PR 6 — `feat(engine): interface de motor e qwen3-tts com streaming e cancelamento`
- [x] PR 7 — `feat(normalize): normalização pt-br com modo incremental e tabela de casos`
- [x] PR 8 — `feat(api): banco, clientes, tokens, vozes e medição por fala`
  Postgres + Alembic; tabelas de [arquitetura.md](arquitetura.md).
- [ ] PR 9 — `feat(api): websocket de streaming com autenticação, admissão e métricas`
- [ ] PR 10 — `chore(infra): imagem cuda, compose de dev e deploy em gpu`

Gate: teste de carga no WebSocket com TTFA p95 ≤ 350 ms no pico previsto, cancelamento < 50 ms.

## Fase 2 — LiveKit em modo híbrido

- [ ] PR 11 — `feat(livekit): plugin de tts com streaming, cancelamento e fallback para elevenlabs`
- [ ] PR 12 — `feat(api): roteamento por cliente e fallback no servidor`
- [ ] PR 13 — `test: carga ponta a ponta com chamadas sip simuladas`
- [ ] Rampa 1% → 10% do tráfego real, 7 dias em cada degrau.

Gate: métricas de [operacao.md](operacao.md) dentro da meta a 10% por 7 dias, sem piora nas métricas de negócio.

## Fase 3 — Lote, WhatsApp, MCP e compatibilidade

- [ ] PR 14 — `feat(api): síntese em lote com ogg opus e entrega por url assinada`
- [ ] PR 15 — `feat(mcp): servidor mcp com synthesize, list_voices e get_voice`
- [ ] PR 16 — `feat(compat): subconjunto da api da elevenlabs`
  Só o que [paridade-elevenlabs.md](paridade-elevenlabs.md) marcar como usado.
- [ ] PR 17 — `feat(normalize): dicionário de pronúncia por cliente`
- [ ] Migrar integrações de WhatsApp para o k-voice.

Gate: nenhuma integração de lote chamando a ElevenLabs direto.

## Fase 4 — Vozes próprias

- [ ] PR 18 — `feat(voices): consentimento registrado e clonagem a partir de referência`
- [ ] PR 19 — `feat(train): preparo de dados e ajuste fino do modelo por voz`
- [ ] PR 20 — `feat(voices): vozes dos locutores no catálogo`
- [ ] Teste cego de novo, agora com as vozes próprias.

Gate: vozes próprias passam no teste cego contra as vozes ElevenLabs equivalentes.

## Fase 5 — Substituição

- [ ] PR 21 — `feat(ops): painéis e alertas de slo`
- [ ] PR 22 — `chore(infra): segundo grupo de nós em outra região ou provedor`
  Substitui a ElevenLabs como fallback.
- [ ] Rampa 50% → 100%.
- [ ] PR 23 — `docs: runbook de desligamento da elevenlabs`
- [ ] 30 dias a 100% dentro do critério de sucesso de [escopo.md](escopo.md) → desligar ou reduzir o plano da ElevenLabs.
