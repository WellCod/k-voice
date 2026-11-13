# Consultas ao banco antes do primeiro áudio no WebSocket

Medição de `bench/consultas_ws.py`. Cada fala no WebSocket faz quatro consultas em sequência antes do `started`: autenticação do token, voz, regra de roteamento e dicionário do cliente. O objetivo é decidir se um cache em memória vale a pena.

## 2026-11-10

| | |
|---|---|
| Máquina | notebook AMD Ryzen 7 7735HS, Windows 11, Postgres 16.15 no Docker Desktop (`docker-compose.dev.yml`) |
| Versões | SQLAlchemy 2.1.6 · asyncpg 0.32.0 · Python 3.12.13 |
| Execução | 300 repetições por etapa depois de 5 de aquecimento, duas rodadas de cada variante |

Faixa das duas rodadas, em ms:

| Etapa | p50 com `pool_pre_ping` | p95 com `pool_pre_ping` | p50 sem | p95 sem |
|---|---|---|---|---|
| Token | 8,6–9,8 | 10–16 | 5,3–7,8 | 6,5–12,6 |
| Voz | 6,5–8,6 | 8,3–13 | 3,8–5,3 | 6,3–7,0 |
| Regra | 6,4–6,7 | 8,1–12 | 3,4–5,0 | 4,2–6,7 |
| Dicionário | 6,7–7,0 | 8,7–12 | 3,9–5,0 | 4,5–7,4 |
| **As quatro em sequência** | **29–30** | **36–45** | **21–26** | **32–40** |
| Token, depois as outras três juntas | 17–27 | 21–49 | 12–16 | 25 |

O servidor usa `pool_pre_ping=True`, que acrescenta uma ida ao banco por sessão: de 2 a 3 ms por consulta. Rodar a voz, a regra e o dicionário juntos tira de 4 a 13 ms da mediana, mas o p95 fica no mesmo patamar. O ruído entre rodadas é alto: o banco roda numa VM do Docker Desktop.

Conclusão: com o banco local, as consultas custam de 30 a 45 ms do orçamento de 350 ms do p95 do TTFA, ou seja, de 9% a 13%. Em produção, com o banco na rede, o custo por consulta tende a ser maior. Um cache em memória com validade curta para token, voz, regra e dicionário, invalidado pelas rotas de admin, tira quase todo esse custo. Paralelizar ou desligar o `pre_ping` só tira parte. O número que decide é o TTFA em GPU com e sem o cache ([gpu-nuvem.md](../gpu-nuvem.md)).

Para refazer, com o Postgres de dev no ar e `alembic upgrade head`:

```bash
uv run python -m bench.consultas_ws --n 300
uv run python -m bench.consultas_ws --n 300 --sem-pre-ping
```

O script cria um cliente, um token, uma voz e uma entrada de dicionário temporários e apaga tudo no fim. O JSON fica em `bench/outputs/consultas_ws/`, fora do git.

## Com o cache de consultas — 2026-11-12

Mesma máquina e versões. Token, voz, regra e dicionário passaram a ficar em memória por `QUERY_CACHE_TTL_S` (30 s); a variante `sequencia_com_cache` mede as quatro com o cache já preenchido, e as demais rodam com o cache desligado para seguirem medindo o banco. Duas rodadas, 300 repetições, em ms:

| Etapa | p50 | p95 | max |
|---|---|---|---|
| As quatro em sequência, sem cache | 28–30 | 37–40 | 67–110 |
| As quatro em sequência, com cache | 0,01 | 0,01 | 0,02–0,05 |

A partir da segunda fala do mesmo cliente dentro da validade, as consultas saem do custo do primeiro áudio. A primeira fala de cada cliente, e a primeira depois de uma escrita no admin, ainda vai ao banco.
