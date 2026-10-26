# Modelos de voz

Situação levantada em 2026-10-26. A área muda rápido: revisar a cada 6 meses e antes de qualquer troca. Licença vale a dos **pesos**, conferida no model card, não a do código.

## Candidatos

### Qwen3-TTS (Alibaba, time Qwen) — principal
- Repositório: github.com/QwenLM/Qwen3-TTS. Pesos: huggingface.co/Qwen (ex.: `Qwen3-TTS-12Hz-1.7B-Base`).
- Licença: Apache-2.0 (repositório e model card).
- Tamanhos: 0.6B e 1.7B.
- Variantes: Base (clonagem com ~3 s de referência), CustomVoice (vozes prontas + instrução de estilo), VoiceDesign (voz por descrição em texto).
- Idiomas: zh, en, ja, ko, de, fr, ru, **pt**, es, it.
- Streaming: sim; o fabricante cita primeiro pacote após um caractere e latência "a partir de 97 ms".
- Medição de terceiros (pacote `faster-qwen3-tts`, 0.6B, CUDA graphs): TTFA ~156 ms numa RTX 4090, ~228 ms numa H100, ~901 ms numa T4. RTF ~4,8x tempo real na 4090.
- A conferir na Fase 0: qualidade em pt-BR (sotaque brasileiro vs europeu), estabilidade em frases longas, concorrência real.

### Chatterbox Multilingual + finetune pt-BR (Resemble AI) — comparação
- Repositório: github.com/resemble-ai/chatterbox. Finetune: `ResembleAI/Chatterbox-Multilingual-pt-br`.
- Licença: MIT (conferir o model card do finetune pt-BR).
- ~500M parâmetros; 23+ idiomas; finetune dedicado a pt-BR.
- Clonagem com ~5 s; controle de intensidade de emoção.
- Marca d'água Perth em todo áudio gerado, detectável por ferramenta aberta. Não remover.
- Sem streaming oficial nos modelos abertos; Turbo (rápido) é só inglês.

### Kokoro-82M — piso de latência
- Apache-2.0, vozes pt-BR, roda em CPU, sem clonagem, pouca expressividade. Serve de referência baixa no teste cego e de fallback barato.

### A acompanhar
- Pocket TTS (Kyutai): código MIT, pesos CC-BY-4.0, CPU, português; clonagem só na versão de acesso restrito.
- Sopro V2 Turbo: Apache-2.0, streaming; cobre português europeu, conferir pt-BR.
- MOSS-TTS-Nano: streaming em CPU; licença e pt-BR não conferidos.

## Descartados

| Modelo | Motivo |
|---|---|
| Voxtral TTS (Mistral) | pesos CC BY-NC 4.0; comercial só pela API da Mistral |
| Fish Audio S2 | Fish Audio Research License; comercial exige licença paga |
| XTTS-v2 (Coqui) | Coqui Public Model License, não comercial |
| F5-TTS | pesos CC-BY-NC |
| OmniVoice (padrão do VoiceStudio) | pesos CC-BY-NC |
| CosyVoice 3 | Apache-2.0, mas sem português |
| Orpheus | pesos herdam termos da família Llama; foco em inglês |
| Modelos voz-para-voz full duplex (Moshi, PersonaPlex etc.) | sem pt-BR de qualidade de produção; a cadeia STT → LLM → TTS continua o caminho prático |

## Fontes

- github.com/QwenLM/Qwen3-TTS · huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base · pypi.org/project/faster-qwen3-tts
- github.com/resemble-ai/chatterbox · huggingface.co/ResembleAI/chatterbox
- github.com/FunAudioLLM/CosyVoice · huggingface.co/mistralai/voxtral-4b-tts-2603 · kyutai.org/next/tts
- coval.ai/blog/tts-latency-benchmark-2026 · codebridge.tech/articles/voice-ai-phone-agents-latency-benchmark · arxiv.org/abs/2603.05413v2
