# Teste cego (gate da Fase 0 e de cada troca de modelo ou voz)

## O que se mede

1. **Qualidade percebida** em condição de ligação, não em fone de estúdio.
2. **Latência** até o primeiro som, isolada e sob concorrência.

## Motores comparados

| Motor | Papel |
|---|---|
| ElevenLabs (modelo e vozes usados hoje em produção) | referência |
| Qwen3-TTS 0.6B e 1.7B | candidato principal |
| Chatterbox Multilingual pt-BR | candidato |
| Kokoro-82M | piso: se ninguém percebe diferença nem para ele, o teste está mal montado |

Para cada motor, escolher a voz mais próxima (gênero, idade, timbre) das 2 vozes ElevenLabs mais usadas. Para Qwen3-TTS e Chatterbox, testar também clonagem a partir de ~10 s de uma voz com consentimento.

## Conjunto de frases (`bench/frases.yaml`)

~60 frases, tiradas de transcrições reais do produto (sem dado pessoal), cobrindo:
- saudação e abertura de ligação;
- confirmação curta ("perfeito", "entendi, só um instante");
- frases com moeda, data, hora, telefone, CPF, endereço, siglas;
- frases longas (3+ orações) e perguntas;
- emoção: empatia ("sinto muito pelo transtorno"), entusiasmo, firmeza;
- hesitações e marcadores de fala ("então...", "deixa eu ver aqui").

Todo texto passa pelo mesmo normalizador antes de todos os motores, inclusive a ElevenLabs.

## Condição de escuta

Cada áudio é avaliado em duas versões:
- **Telefone:** reamostrado para 8 kHz, μ-law, passa-banda 300–3400 Hz. É a condição que decide.
- **WebRTC:** Opus 48 kHz (ligação pelo app, se existir).

Normalizar a loudness de todos (por exemplo −16 LUFS) para volume não influenciar.

## Protocolo

- **ABX:** o ouvinte escuta A (ElevenLabs), B (candidato) e X (um dos dois) e diz qual é X. Mínimo de 20 ouvintes, 30 julgamentos cada, ordem aleatória.
- **MOS de naturalidade:** nota de 1 a 5 por áudio, sem saber o motor.
- **Preferência:** em pares, "qual soa mais como uma pessoa ao telefone?".
- Ouvintes: brasileiros, de fora do time técnico de voz. Incluir pessoas do atendimento, que ouvem ligações todo dia.

## Critérios para passar

| Critério | Meta |
|---|---|
| ABX em áudio de telefone | acerto ≤ 60% (não distinguem com segurança; teste binomial, p > 0,05 contra 50%) |
| MOS em áudio de telefone | ≥ MOS da ElevenLabs − 0,2 |
| Preferência | candidato ≥ 40% |
| Erros de leitura (número, sigla, nome) | 0 no conjunto |
| TTFA p50 / p95 com 1 stream | ≤ 200 / ≤ 300 ms |
| TTFA p95 no pico de concorrência previsto | ≤ ElevenLabs medida da mesma região + 50 ms |
| Estabilidade | 0 falas com artefato grave (corte, eco, repetição, troca de voz) em 500 gerações |

## Latência — como medir

- TTFA = do envio do primeiro pedaço de texto até o primeiro byte de áudio **reproduzível** (não cabeçalho).
- Texto chegando em pedaços de 3–8 palavras, como sai de um LLM.
- Medir com 1, 4, 8, 16 e 32 streams simultâneos na GPU-alvo. Registrar p50, p95, p99 e RTF.
- ElevenLabs medida a partir de uma máquina na mesma região do LiveKit.

## Resultado

Registrar em `docs/resultados/fase-0.md`: números, CSV das respostas, 5 áudios de exemplo por motor e a decisão.
