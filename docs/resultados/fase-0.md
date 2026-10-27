# Resultado — Fase 0 (gate de existência do projeto)

**Pergunta:** algum modelo aberto, com licença comercial, empata com a ElevenLabs em áudio de telefone pt-BR e aguenta a concorrência com latência na meta?

---

## Infraestrutura de medição

Os scripts abaixo foram implementados nos PRs 2–4 e cobrem todas as medições exigidas pelo gate.

| Script | O que faz |
|---|---|
| `bench/sintetizar.py` | Sintetiza `bench/frases.yaml` em cada motor e grava WAV + JSONL |
| `bench/degradar.py` | Aplica pipeline de telefone (8 kHz μ-law) e Opus 48 kHz |
| `bench/gerar_teste.py` | Gera `bench/teste_cego/dados.js` para a página de teste |
| `bench/teste_cego/index.html` | Página de ABX, MOS e preferência com exportação CSV |
| `bench/analisar.py` | Lê o CSV e calcula acerto ABX + binomial, MOS com IC 95%, preferência |
| `bench/latencia.py` | Mede TTFA e RTF com 1, 4, 8, 16, 32 streams simultâneos |

---

## Como executar

```bash
# 1. Síntese (requer GPU; instalar faster-qwen3-tts, chatterbox-tts, kokoro separadamente)
uv run --group bench python -m bench.sintetizar --motores todos --condicao tel

# 2. Degradação
uv run --group bench python -m bench.degradar --condicao tel

# 3. Teste cego (abrir no navegador após gerar dados.js)
uv run --group bench python -m bench.gerar_teste --motor-ref elevenlabs --condicao tel
open bench/teste_cego/index.html

# 4. Análise das respostas (CSV exportado pela página)
uv run --group bench python -m bench.analisar bench/teste_cego/respostas.csv --condicao tel

# 5. Latência e concorrência
uv run --group bench python -m bench.latencia --motores todos --concorrencias 1,4,8,16,32 --repeticoes 5
```

---

## Critérios do gate

Ver protocolo completo em [teste-cego.md](../teste-cego.md).

| Critério | Meta |
|---|---|
| ABX em áudio de telefone | acerto ≤ 60% (p > 0,05 contra 50% no teste binomial) |
| MOS em áudio de telefone | ≥ MOS da ElevenLabs − 0,2 |
| Preferência | candidato ≥ 40% |
| Erros de leitura (número, sigla, nome) | 0 no conjunto |
| TTFA p50 / p95 com 1 stream | ≤ 200 ms / ≤ 300 ms |
| TTFA p95 no pico de concorrência | ≤ TTFA p95 ElevenLabs + 50 ms |
| Estabilidade | 0 artefatos graves em 500 gerações |

---

## Resultados

> A preencher após execução com hardware GPU e painel de ouvintes (mín. 20, 30 julgamentos cada).
> Hardware, versão do modelo e data são obrigatórios em cada seção.

### Hardware e ambiente

| Item | Valor |
|---|---|
| GPU | — |
| VRAM | — |
| Driver CUDA | — |
| faster-qwen3-tts | — |
| Data da medição | — |
| Região de rede (ElevenLabs) | — |

### Qualidade — ABX (condição telefone)

| Motor | n | acertos | % | p-valor | Gate |
|---|---|---|---|---|---|
| Qwen3-TTS 0.6B | — | — | — | — | — |
| Qwen3-TTS 1.7B | — | — | — | — | — |
| Chatterbox pt-BR | — | — | — | — | — |
| Kokoro-82M | — | — | — | — | — |

### Qualidade — MOS (condição telefone)

| Motor | n | média | IC 95% | Gate |
|---|---|---|---|---|
| ElevenLabs (ref) | — | — | — | — |
| Qwen3-TTS 0.6B | — | — | — | — |
| Qwen3-TTS 1.7B | — | — | — | — |
| Chatterbox pt-BR | — | — | — | — |
| Kokoro-82M | — | — | — | — |

### Qualidade — Preferência (condição telefone)

| Par | n | candidato | % | Gate |
|---|---|---|---|---|
| ElevenLabs vs Qwen3-TTS 0.6B | — | — | — | — |
| ElevenLabs vs Qwen3-TTS 1.7B | — | — | — | — |
| ElevenLabs vs Chatterbox pt-BR | — | — | — | — |
| ElevenLabs vs Kokoro-82M | — | — | — | — |

### Erros de leitura

> 0 erros é o critério. Listar qualquer frase em que o áudio não correspondeu ao texto esperado.

| Motor | Frase id | Texto | Lido como |
|---|---|---|---|
| — | — | — | — |

### Estabilidade

> 500 gerações por motor. Listar os casos com artefato (corte, eco, repetição, troca de voz).

| Motor | Falhas | Exemplos |
|---|---|---|
| Qwen3-TTS | — | — |
| Chatterbox pt-BR | — | — |

### Latência e concorrência

> Arquivo bruto: `bench/outputs/latencia_{motor}_{ts}.jsonl`

#### ElevenLabs (referência, mesma região do LiveKit)

| Conc. | TTFA p50 | TTFA p95 | RTF p50 |
|---|---|---|---|
| 1 | — | — | — |
| 4 | — | — | — |
| 8 | — | — | — |
| 16 | — | — | — |
| 32 | — | — | — |

#### Qwen3-TTS 0.6B (streaming)

| Conc. | TTFA p50 | TTFA p95 | RTF p50 | Gate 1-stream | Gate pico |
|---|---|---|---|---|---|
| 1 | — | — | — | — | — |
| 4 | — | — | — | — | — |
| 8 | — | — | — | — | — |
| 16 | — | — | — | — | — |
| 32 | — | — | — | — | — |

#### Qwen3-TTS 1.7B (streaming)

| Conc. | TTFA p50 | TTFA p95 | RTF p50 |
|---|---|---|---|
| 1 | — | — | — |
| 4 | — | — | — |
| 8 | — | — | — |

### Áudios de exemplo

> 5 frases por motor, cobrindo: saudação, confirmação, moeda, frase longa, emoção. Gravar na condição `tel`.

Arquivos em `bench/outputs/`, não versionados. Incluir caminhos relativos aqui após execução.

---

## Decisão

> Preencher após consolidar todos os resultados acima.

**Motor escolhido:** —

**Critérios atendidos:** —

**Critérios não atendidos:** —

**Decisão:**
- [ ] Gate cumprido → ADR-0002 muda para `aceito`; iniciar Fase 1.
- [ ] Gate não cumprido → projeto pausa; próxima revisão em 6 meses ou quando modelo melhor for lançado (ver `docs/escopo.md` § critério de parada).

---

## Referência

- Protocolo completo: [docs/teste-cego.md](../teste-cego.md)
- Modelos avaliados: [docs/modelos.md](../modelos.md)
- Decisão de motor: [docs/adr/0002-qwen3-tts-motor-inicial.md](../adr/0002-qwen3-tts-motor-inicial.md)
