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

## Conjunto completo — 2026-11-06

As 67 frases de `bench/frases.yaml`, normalizador já corrigido. Mesma máquina, versões, motor e ASR da base. Rótulo `qwen3-0.6b-cpu-completo`, uma execução; síntese de 15 s a 147 s por frase, cerca de 50 min no total.

| Categoria | Frases | WER | CER |
|---|---|---|---|
| Hesitação | 5 | 10,4% | 2,4% |
| CPF | 2 | 10,4% | 3,1% |
| Siglas | 5 | 5,2% | 2,1% |
| CNPJ | 2 | 2,2% | 2,3% |
| Firmeza | 4 | 1,8% | 0,7% |
| Saudação, confirmação, moeda, data, telefone, endereço, frase longa, pergunta, empatia, entusiasmo | 48 | 0% | 0% |
| **Total** | **67** | **1,7%** | **0,5%** |

57 das 67 frases sem nenhuma diferença, incluindo as 5 frases longas (até 147 s de síntese), as perguntas e as de emoção. As 10 com diferença, separadas pela causa provável:

**Normalizador (corrigível no k-voice)**

| Frase | Diferença | Causa |
|---|---|---|
| `siglas_04` — "O SLA de atendimento" | "SLA de" ouvido como "slide" | `SLA` tem vogal, então `_acronimo` a trata como palavra e manda "sla" para a voz, que lê como palavra. Falta em `_PALAVRAS_NATIVAS` como "esse ele á". O mesmo vale para outras siglas com vogal fora da lista (ex.: `URL` sai "url"). |

**Voz**

| Frase | Diferença | Observação |
|---|---|---|
| `cnpj_01` — "0001" | um zero a menos | Na base saiu um zero a mais. Nas duas execuções o "zero zero zero um" saiu errado, em direções opostas: a voz se perde em dígito repetido. |
| `hesitacao_01` — "deixa eu ver" | ouvido "deixe-o ver" | A voz junta "deixa eu" em "deix'eu", como na fala coloquial. Aceitável. |

**ASR ou comparação (a voz provavelmente acertou)**

| Frase | Diferença | Observação |
|---|---|---|
| `cpf_01`, `cpf_02`, `hesitacao_05`, `siglas_01` | "C-PF", "CPFE", "CP e Fê", "CNP, J" | O Whisper escreve a sigla soletrada de jeitos que a comparação não reconhece como CPF ou CNPJ. |
| `siglas_02` — "TED" | ouvido "TD" | Mesmo caso: "tê ê dê" escrito como "TD". |
| `hesitacao_02` — "Hmm" | ouvido "Hum" | Grafia da interjeição. |
| `firmeza_04` — "alçada alterar" | ouvido "alçada a alterar" | Uma palavra a mais; pode ser a voz ou o ASR. |

Fora o `SLA`, nada aqui pede mudança no motor. A hesitação aparece como pior categoria por grafia do ASR, não por pronúncia.

Para refazer: `uv run --group bench python -m bench.pronuncia --motor qwen3-cpu --rotulo qwen3-0.6b-cpu-completo`.

## Depois de soletrar siglas com vogal — 2026-11-06

`SLA`, `URL`, `KPI`, `ERP`, `UTI` e `IPCA` entraram em `_PALAVRAS_NATIVAS`; antes iam para a voz como palavra ("sla", "url"). As 5 frases de sigla sintetizadas de novo (`--categoria normalizacao_siglas`, rótulo `qwen3-0.6b-cpu-siglas-fix`), mesma máquina, versões, motor e ASR.

| Frase | Antes | Depois |
|---|---|---|
| `siglas_04` — "O SLA de atendimento" | "slide atendimento" (17% com o "de") | "ESL de atendimento" (17%) |

O WER de `siglas_04` não mudou, mas o erro mudou de natureza: a voz passou a soletrar e o Whisper escreveu as letras como "ESL", que a comparação não casa com "esse ele á". O "slide" sumiu.

Na mesma execução, `siglas_01` e `siglas_02` saíram com 0% (antes 6% e 7%) e `siglas_03` caiu de 0% para 10% ("apólice" ouvido "A pólice"), sem mudança no texto que essas frases mandam para a voz. É a variação de uma execução para outra, do mesmo tamanho das diferenças medidas; comparar sigla a sigla pede várias execuções por frase.

## Dicionário ampliado — 2026-11-10

Siglas com vogal (AVC, EUA, IR, CEO, SUV, UFRJ…), siglas que também são palavras (IR, TI, UE só em maiúscula), notas fiscais, 4G/5G, MP3 e anglicismos de atendimento e marcas ("e-mail" → "imeio", "site" → "sáite", "Ok" → "oquei", Google, Nubank…). Das 67 frases de `bench/frases.yaml`, três mudam de texto normalizado: `confirmacao_06` ("Ok"), `pergunta_03` e `longa_05` ("e-mail"). As categorias delas foram sintetizadas de novo (mesma máquina, motor e ASR da base; rótulos `qwen3-0.6b-cpu-dicionario-*`):

| Categoria | Frases | WER | Frases que mudaram |
|---|---|---|---|
| Confirmação | 6 | 0% | `confirmacao_06`: 0% |
| Pergunta | 5 | 1,7% | `pergunta_03`: 0% |
| Frase longa | 5 | 0,7% | `longa_05`: 0% |

As três frases alteradas seguem sem erro. As duas diferenças são em frases de texto inalterado: `pergunta_02` ("caia" saiu "caiaia", repetição da voz) e `longa_02` ("apólice" ouvido "a pólice", já visto em `siglas_03`), variação de uma execução para outra.
