# ADR-0005 — Normalização de texto pt-BR própria, antes de qualquer motor

- Estado: aceito
- Data: 2026-10-26

## Contexto

Modelos abertos erram leitura de moeda, datas, CPF, siglas e números com mais frequência que a ElevenLabs. Numa ligação, um "R$ 1.234,50" lido errado denuncia a máquina na hora.

## Decisão

Módulo próprio, determinístico, aplicado a todo texto antes do motor, inclusive quando o motor é a ElevenLabs. Suporta texto incremental (só emite até um limite seguro). Dicionário de pronúncia por cliente.

## Consequências

- A pronúncia fica igual entre k-voice e ElevenLabs, o que torna o teste cego justo e o fallback menos perceptível.
- Mais um componente a manter, coberto por tabela de casos.
