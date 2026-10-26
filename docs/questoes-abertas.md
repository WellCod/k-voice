# Questões abertas

Responder antes da fase indicada. Registrar a resposta aqui (e em ADR, se for decisão de arquitetura).

| # | Questão | Por que importa | Antes da |
|---|---|---|---|
| 1 | O agente LiveKit é Python ou Node? Qual versão do LiveKit Agents? LiveKit Cloud ou self-hosted? Em que nuvem e região? | Linguagem do plugin; região das GPUs | Fase 0 (PR 4) |
| 2 | Qual modelo e quais vozes da ElevenLabs estão em produção? | Referência do teste cego | Fase 0 (PR 2) |
| 3 | Caracteres e minutos por mês, pico de ligações simultâneas e horário | Capacidade e custo | Fase 0 (PR 5) |
| 4 | Onde a ElevenLabs é chamada fora do agente (WhatsApp, outros)? | Inventário de paridade e camada compat | Fase 3 |
| 5 | Provedor de GPU: mesma nuvem do LiveKit, RunPod, Lambda, outro? Alguém no time já opera GPU? | Latência de rede e custo de operação | Fase 1 (PR 10) |
| 6 | Bucket: S3, GCS, R2? Retenção do áudio de lote? | Entrega de WhatsApp e LGPD | Fase 3 |
| 7 | Clientes precisam de voz clonada própria (voz da marca)? | Prioridade da Fase 4 | Fase 4 |
| 8 | Proposta empresarial da ElevenLabs e preços de Cartesia/Inworld em pt-BR | Comparação de custo real | Fase 0 (PR 5) |
| 9 | Quem são os ouvintes do teste cego? | Validade do gate | Fase 0 (PR 3) |
| 10 | O repositório vai para GitHub da empresa? Nome e visibilidade? | CI e fluxo de PR | Fase 0 (PR 1) |
