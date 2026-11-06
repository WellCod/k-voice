# Bench de pronúncia num Mac com Apple Silicon

Roteiro para rodar `bench/pronuncia.py` num Mac (M1 a M5) e comparar o Qwen3-TTS 0.6B com o 1.7B. O motor é o mesmo `Qwen3TTSEngine` do servidor, com o torch na GPU do Mac (MPS).

O que este roteiro mede e o que não mede:

- Mede a pronúncia (WER e CER) do 0.6B e do 1.7B com os mesmos pesos e o mesmo código do servidor.
- Não mede latência de produção. O `faster-qwen3-tts`, motor de streaming em produção, exige CUDA. Tempo até o primeiro áudio e concorrência continuam no roteiro de GPU ([gpu-nuvem.md](gpu-nuvem.md)).
- O Whisper (faster-whisper, CTranslate2) não usa a GPU do Mac: a transcrição roda na CPU.

O Qwen3-TTS em MPS ainda não foi rodado neste repositório. Se alguma operação faltar no MPS, o passo 4 diz o que tentar.

## 1. Memória

16 GB bastam: o 1.7B em bfloat16 tem cerca de 3,5 GB de pesos e o Whisper large-v3 em int8 cerca de 1,5 GB. Feche navegador e IDE pesados durante a execução do 1.7B.

Disco: cerca de 8 GB no cache do Hugging Face (`~/.cache/huggingface`) para os dois modelos de voz e o Whisper.

## 2. Preparar o código

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/WellCod/k-voice.git
cd k-voice
uv sync --group bench
```

O `uv.lock` já traz as wheels do torch e do ctranslate2 para macOS arm64.

## 3. Conferir o torch

```bash
uv run python -c "import torch; print(torch.__version__, torch.backends.mps.is_available())"
```

Tem que imprimir `True`. Se imprimir `False`, o macOS é antigo para a wheel do torch (pede macOS 14 ou mais novo).

## 4. Teste curto

```bash
uv run --group bench python -m bench.pronuncia --motor qwen3-mps --limite 3 --rotulo teste-mps
```

Se falhar:

- Erro de operação não implementada no MPS: rode de novo com `PYTORCH_ENABLE_MPS_FALLBACK=1` na frente do comando. As operações que faltam vão para a CPU.
- Erro de tipo ou áudio com ruído: troque o bfloat16 por float32 com `--dtype float32` (usa o dobro de memória).
- Anote a combinação que funcionou: ela vale para as duas execuções seguintes e entra no registro.

## 5. 0.6B contra 1.7B

As 67 frases em cada modelo, mesmo speaker e mesmo ASR:

```bash
uv run --group bench python -m bench.pronuncia --motor qwen3-mps \
    --modelo-tts Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --rotulo qwen3-0.6b-mps
uv run --group bench python -m bench.pronuncia --motor qwen3-mps \
    --modelo-tts Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --rotulo qwen3-1.7b-mps
```

Cada frase grava o resultado assim que termina. Se a execução cair no meio, repita o comando com `--reaproveitar` para não sintetizar de novo o que já está pronto.

Para ouvir: os WAV ficam em `bench/outputs/pronuncia/<rotulo>/`, um por frase. Vale ouvir em especial as frases de sigla, de CPF e CNPJ e de hesitação, que concentram as diferenças medidas em CPU ([resultados/pronuncia.md](resultados/pronuncia.md)).

## 6. Trazer os resultados

De cada rótulo, os arquivos `resumo.json` e `resultado.jsonl` (os WAV são opcionais). Eles entram em `docs/resultados/pronuncia.md` com máquina, macOS, versões, dtype e se o fallback de CPU foi usado.
