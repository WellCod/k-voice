# Pronúncia medida por transcrição automática

Medições de `bench/pronuncia.py`: sintetiza as frases de `bench/frases.yaml`, transcreve com o Whisper e compara com o texto esperado, os dois lados passados pela normalização do k-voice. Documento, telefone e CEP são comparados pelos dígitos, não pelo agrupamento que o ASR escolhe.

A taxa de erro mistura erro da voz com erro do ASR. Serve para comparar motor, modelo e versão no mesmo ASR e para achar as piores frases; não é medida absoluta de qualidade. A decisão de qualidade continua sendo o teste cego ([teste-cego.md](../teste-cego.md)).

## Base — 2026-11-06

| | |
|---|---|
| Motor | `Qwen3TTSEngine` em CPU, `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, float32, speaker `vivian` |
| ASR | `faster-whisper` 1.2.1, `large-v3`, CPU int8, `language="pt"`, beam 5 |
| Máquina | notebook AMD Ryzen 7 7735HS, Windows 11, sem GPU NVIDIA |
| Versões | kvoice 0.1.0 · faster-qwen3-tts 0.5.4 · qwen-tts-hf 0.1.1.post1 · torch 2.14.1+cpu · transformers 5.16.1 · ctranslate2 4.8.5 |
| Frases | as 27 de normalização (`--categoria normalizacao`), uma execução |

| Categoria | Frases | WER | CER |
|---|---|---|---|
| CPF | 2 | 7,9% | 2,1% |
| CNPJ | 2 | 2,2% | 2,3% |
| Telefone | 4 | 1,4% | 1,3% |
| Siglas | 5 | 1,2% | 0,2% |
| Moeda | 6 | 0% | 0% |
| Data | 5 | 0% | 0% |
| Endereço (CEP) | 3 | 0% | 0% |
| **Total** | **27** | **1,2%** | **0,6%** |

23 das 27 frases sem nenhuma diferença. As quatro com diferença:

| Frase | Diferença | Causa provável |
|---|---|---|
| `telefone_04` — "ligue para 0800 123 4567" | falta o "zero" inicial | normalizador lê `0800 123 4567` como "oitocentos cento e vinte e três quatro mil...", não como dígitos |
| `cpf_02` — "CPF 987.654.321-00" | "CPF" transcrito como "CPE F" | voz ou ASR; ouvir `cpf_02.wav` |
| `siglas_01` — "CPF ... CNPJ" | "CNPJ" transcrito como "CMPJ" | o "ene" soletrado saiu parecido com "eme" |
| `cnpj_01` — "12.345.678/0001-99" | um zero a mais | voz repetiu o zero ou o ASR inseriu |

Fora do conjunto de frases, ao montar o bench apareceram dois erros do normalizador que esta medição não cobre:

- número com 13 dígitos ou mais derruba `normalize()` com `IndexError` (protocolo, código de barras, pedido);
- telefone sem parênteses (`11 98765-4321`, `98765-4321`, `11987654321`, `+55 11 ...`, `4002-8922`) é lido como número grande.

Para refazer: `uv run --group bench python -m bench.pronuncia --motor qwen3-cpu --categoria normalizacao --rotulo qwen3-0.6b-cpu`. Os WAV, `resultado.jsonl` e `resumo.json` ficam em `bench/outputs/pronuncia/<rotulo>/` (fora do git).

## Depois da correção do normalizador — 2026-11-06

Telefone em todos os formatos, 0800, separador de milhar, decimal e números longos (`fix(normalize)`). Mesma máquina, versões, motor e ASR da base; as 4 frases de telefone sintetizadas de novo (`--categoria normalizacao_telefone`).

| Categoria | Frases | WER antes | WER depois |
|---|---|---|---|
| Telefone | 4 | 1,4% | 0% |

`telefone_04` ("0800 123 4567") passou a ser falado "zero oitocentos, um dois três, quatro cinco seis sete", e o "zero" que faltava aparece na transcrição. Os dois erros fora do conjunto de frases (crash com 13+ dígitos e telefone sem parênteses) estão cobertos por casos em `tests/normalize/casos.yaml`.
