# Custos

Preços de GPU abaixo são ordem de grandeza de out/2026, não cotação. Refazer com cotação real e com os números de [paridade-elevenlabs.md](paridade-elevenlabs.md).

## Hoje

- ElevenLabs: ~US$ 5.000/mês, crescendo linearmente com o volume.

## k-voice

### Infraestrutura

| GPU (nuvem) | US$/h aprox. | 24/7 por mês |
|---|---|---|
| RTX 4090 / L4 | 0,40–0,80 | 300–600 |
| L40S / A10G | 1,00–1,50 | 750–1.100 |
| H100 | 2,00–3,00 | 1.500–2.200 |

### Capacidade (hipótese a medir na Fase 0)

- Qwen3-TTS 0.6B numa 4090: RTF ~4,8x → ~4 falas geradas ao mesmo tempo com folga.
- A IA fala ~30–50% do tempo da ligação → **~8–12 ligações simultâneas por GPU**.
- Mínimo de 2 GPUs para redundância.

```
GPUs = max(2, ceil(pico_de_ligações_simultâneas / ligações_por_gpu_medidas) + 1)
custo_infra = GPUs × custo_hora × horas_ligadas
```

Se o tráfego for concentrado em horário comercial, escalar para baixo fora do horário (mantendo 2 nós).

Exemplo com pico de 20–30 ligações: 3–4 GPUs, ~US$ 1.200–2.500/mês.

### Custos que não estão na fatura

| Item | Estimativa |
|---|---|
| Construção (Fases 0–3) | 1–2 meses de um engenheiro, com agente de IA |
| Operação contínua | horas por mês de monitoramento, atualização, plantão |
| Vozes próprias (Fase 4) | cachê e contrato de 3–5 locutores, estúdio, GPU para ajuste fino |
| ElevenLabs durante a transição | cai na proporção do tráfego desviado |

## Ponto de equilíbrio

```
economia_mensal = gasto_elevenlabs − (custo_infra + custo_operação_mensal)
meses_para_pagar = custo_construção / economia_mensal
```

Com os números do exemplo: economia de ~US$ 2.500–3.800/mês, ~US$ 30–45 mil/ano.

## Alternativas a comparar antes de investir

1. Proposta de plano empresarial da ElevenLabs (e modelo Flash, normalmente mais barato).
2. Outros provedores pagos com plugin no LiveKit (Cartesia, Inworld, Deepgram etc.), conferindo preço e qualidade em pt-BR.

Se uma alternativa paga cortar 30–50% sem engenharia, comparar esse cenário, e não o preço atual, com o k-voice.
