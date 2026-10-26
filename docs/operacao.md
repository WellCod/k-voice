# Operação

## SLOs

| SLO | Meta | Janela |
|---|---|---|
| TTFA p95 no WebSocket (servidor) | ≤ 350 ms | 5 min |
| Falas atendidas pelo k-voice sem fallback | ≥ 99,5% | 1 dia |
| Disponibilidade do streaming | 99,9% | 30 dias |
| Cancelamento (cancel → último byte) | ≤ 50 ms p95 | 5 min |
| Lote: tempo até URL pronta, por 1.000 caracteres | ≤ 2 s p95 | 1 h |

## Métricas (Prometheus em `/metrics`)

- `kvoice_ttfa_seconds` (histograma; labels: engine, voice, model, node)
- `kvoice_stream_active` e `kvoice_queue_depth` por nó
- `kvoice_rtf` por nó
- `kvoice_fallback_total` (labels: motivo = capacity, error, timeout, rule)
- `kvoice_characters_total`, `kvoice_audio_seconds_total` (labels: client, engine)
- `kvoice_cancel_latency_seconds`
- GPU: uso, memória, temperatura (exporter da NVIDIA)

## Métricas de negócio (vêm do agente / LiveKit)

Comparar k-voice vs ElevenLabs no mesmo período e cliente:
- duração média da ligação;
- taxa de conclusão do objetivo da ligação;
- desligamento nos primeiros 10 s;
- interrupções do usuário por minuto;
- reclamações que citam a voz.

## Alertas

- TTFA p95 > 350 ms por 5 min → aviso; > 500 ms → crítico.
- Fallback > 2% em 15 min → crítico.
- Nó sem heartbeat por 30 s → tirar do balanceador.
- Fila projetando TTFA acima do orçamento em > 20% dos nós → escalar.

## Capacidade

- Capacidade por GPU = maior número de streams simultâneos com TTFA p95 ≤ 350 ms, medido no PR 4 e refeito a cada troca de modelo, versão ou GPU.
- Manter 30% de folga sobre o pico do mês anterior.

## Plantão (runbook mínimo)

1. Latência subindo: conferir fila e RTF por nó; se saturado, mudar o roteamento para `percentual` menor ou `elevenlabs` (enquanto existir) e escalar.
2. Nó com erro: tirar do balanceador, coletar log, reiniciar.
3. Voz com artefato reportado: registrar `request_id`, texto e voz; reproduzir; adicionar à tabela de regressão.
4. Depois do desligamento da ElevenLabs: o fallback é o segundo grupo de nós (Fase 5).
