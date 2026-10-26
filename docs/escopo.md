# Escopo

## Contexto

O produto é um agente de voz que atende ligações de ponta a ponta. Quem contrata sabe que é IA; o requisito é que a voz soe super realista. A orquestração roda no LiveKit (Agents + SIP) e a voz vem da ElevenLabs, a ~US$ 5 mil/mês. O custo cresce linearmente com o uso.

O fork do VoiceStudio (debpalash/VoiceStudio) foi avaliado e descartado; ver [ADR-0001](adr/0001-servico-proprio-sem-fork.md).

## Objetivos

1. Substituir a ElevenLabs em 100% das ligações sem queda perceptível de qualidade.
2. Reduzir o custo mensal de TTS em pelo menos 50% no volume atual.
3. Atender também o caso de áudio em lote (WhatsApp) com a mesma voz.
4. Ter vozes próprias, licenciadas por contrato, sem depender de biblioteca de terceiro.

## Requisitos funcionais

### RF1 — Síntese em streaming (ligação)
- Entrada: texto incremental (tokens do LLM chegando) ou frase completa, `voice_id`, opções de estilo.
- Saída: PCM 16-bit mono em 24 kHz (padrão LiveKit), em pedaços de 20–40 ms, começando antes do texto terminar.
- Cancelamento imediato quando o usuário interrompe (barge-in): parar de gerar em < 50 ms após o cancel.
- Uma sessão por fala; várias falas por ligação.

### RF2 — Síntese em lote (WhatsApp e outros)
- Entrada: texto completo, `voice_id`, formato (`ogg_opus` padrão, `mp3`, `wav`).
- Saída: arquivo gravado no bucket S3 e URL assinada com validade configurável; opção de devolver os bytes direto.
- OGG/Opus mono 48 kHz, compatível com mensagem de voz do WhatsApp.

### RF3 — Normalização de texto pt-BR
- Moeda (`R$ 1.234,50` → "mil duzentos e trinta e quatro reais e cinquenta centavos"), números, ordinais, datas, horas, telefones, CPF/CNPJ, CEP, e-mails, URLs, siglas (lista configurável de soletradas vs lidas), unidades.
- Dicionário de pronúncia por cliente (nome próprio, marca).
- Determinística e testada por tabela de casos; roda antes do modelo, nos dois modos.

### RF4 — Vozes
- Catálogo com `voice_id`, nome, gênero, faixa etária, estilo, idioma, origem (preset do modelo, clonada, ajuste fino) e licença/contrato.
- Criar voz por clonagem a partir de áudio de referência, só com termo de consentimento registrado.
- Fase 4: vozes de 3–5 locutores contratados, com ajuste fino.

### RF5 — Roteamento híbrido
- Por cliente/agente: `kvoice`, `elevenlabs` ou `percentual` (canário).
- Fallback automático para a ElevenLabs quando o k-voice estourar orçamento de latência ou falhar, sem cair a ligação.
- Mapeamento de voz k-voice ↔ voz ElevenLabs para o fallback manter o mais próximo possível.

### RF6 — Compatibilidade com a API da ElevenLabs
- Implementar só os endpoints e parâmetros que o produto usa hoje (inventário em [paridade-elevenlabs.md](paridade-elevenlabs.md)).
- Objetivo: quem chama a ElevenLabs direto troca só URL base e chave.

### RF7 — MCP
- Servidor MCP (Streamable HTTP, autenticado por token) com tools `synthesize`, `list_voices`, `get_voice`.
- Streaming de áudio não passa pelo MCP; ver [ADR-0006](adr/0006-mcp-so-para-lote.md).

### RF8 — Medição
- Registrar por requisição: cliente, voz, modelo, caracteres, segundos de áudio, TTFA, tempo total, motor usado (k-voice/ElevenLabs), fallback e motivo.
- Base para comparação de custo e para o critério de desligamento da ElevenLabs.

## Requisitos não funcionais

| Item | Meta |
|---|---|
| TTFA (texto → primeiro áudio) p50 / p95, medido no servidor | ≤ 200 ms / ≤ 350 ms |
| TTFA com o pico de concorrência previsto | ≤ ElevenLabs + 50 ms |
| Fator de tempo real (RTF) por stream sob carga | < 0,5 (gera 2x mais rápido que fala) |
| Disponibilidade do serviço de streaming | 99,9% mensal, com fallback cobrindo o resto |
| Qualidade (teste cego, áudio de telefone) | ouvintes não distinguem k-voice de ElevenLabs acima do acaso; MOS ≥ ElevenLabs − 0,2 |
| Erros de normalização no conjunto de teste | 0 nos casos da tabela |
| Segurança | token por cliente, TLS, segredos fora do repositório, áudio de referência de clonagem cifrado em repouso |

## Fora de escopo

- STT, LLM, turn-taking, VAD e telefonia (ficam no LiveKit).
- Painel web completo. Um painel mínimo de vozes pode entrar depois da Fase 3, se pedido.
- Dublagem, audiolivro, efeitos sonoros, música, voz para voz.
- Treinar um modelo de voz do zero. Só ajuste fino sobre modelo aberto.

## Critério de sucesso do projeto

A ElevenLabs é desligada quando, por 30 dias seguidos com 100% do tráfego no k-voice:
1. TTFA p95 dentro da meta;
2. taxa de fallback < 0,5% das falas;
3. nenhuma métrica de negócio das ligações (duração, conclusão, desligamento precoce, reclamação) piora além da variação normal;
4. custo total (GPU + operação) ≤ 50% do gasto anterior com a ElevenLabs no mesmo volume.

## Critério de parada

O projeto para, e o caminho vira trocar de provedor pago ou renegociar, se na Fase 0 nenhum modelo passar no teste cego em áudio de telefone. O teste se repete a cada 6 meses.
