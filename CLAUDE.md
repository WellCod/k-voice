# k-voice — instruções para o agente

Servidor de voz próprio para substituir a ElevenLabs no agente de voz (LiveKit) e no áudio de WhatsApp. Leia `README.md` e `docs/` antes de qualquer trabalho. Decisões estão em `docs/adr/`; se uma mudança contradiz um ADR, avise antes de abrir o PR.

## Protocolo de trabalho

- Um PR por vez, na ordem de `docs/roadmap.md`. Branch, implementação, PR. Draft enquanto incompleto ou com CI vermelho; completo e verde → `gh pr ready`.
- O usuário revisa e aprova. Não começar o próximo PR sem aprovação explícita ("prossiga"), salvo quando ele autorizar uma sequência inteira; nesse caso os PRs saem empilhados (base = branch do anterior). Ao mergear pelo `gh`, trocar antes a base do próximo para `main` (`gh pr edit N --base main`).
- Cada fase termina num gate (`docs/roadmap.md`). Não começar a fase seguinte sem o gate cumprido e registrado.
- Ao fim de cada PR, marcar a caixa em `docs/roadmap.md` e atualizar o doc afetado (README, arquitetura, operacao, `.env.example`).
- Ruff (check e format), mypy e testes rodados localmente antes de qualquer commit.

## Verificar antes de implementar

A área muda rápido. Antes de escrever código contra uma biblioteca externa, confirme a assinatura na doc ou no código da versão fixada:
- Qwen3-TTS (`qwen-tts`): API de streaming, clonagem, instrução de estilo, requisitos de GPU.
- LiveKit Agents: interface de TTS com streaming, cancelamento e adaptador de fallback na versão usada pelo agente.
- ElevenLabs: endpoints e parâmetros usados, só pela doc oficial.
- SDK `mcp` do Python: montagem Streamable HTTP no FastAPI.

Nunca invente formato de API de memória. Se a doc não confirmar, diga.

Antes de adotar qualquer modelo ou versão nova: conferir a licença dos **pesos** no model card e registrar em `docs/modelos.md`. Pesos não comerciais estão fora, sem exceção.

## Medir em vez de supor

Qualquer afirmação sobre latência, capacidade ou qualidade vem de medição no repositório (`bench/`), com hardware, versão e data. Números de fabricante só como referência, marcados como tal.

## Commits

Conventional commits com escopo em português:

```
feat(engine): adiciona streaming com cancelamento no qwen3-tts
fix(normalize): corrige leitura de centavos sem reais
chore(ci): cache do uv no workflow
```

- Assunto em minúscula, sem ponto final, imperativo.
- Corpo só quando o "por quê" não é óbvio pelo diff.
- Sem `Co-Authored-By`, "Generated with" ou qualquer menção a ferramenta, em commit e em PR. Sem emoji.

## Pull requests

- Branch: `feat/`, `fix/`, `chore/`, `test/`, `refactor/`, `docs/`.
- Descrição simples e proporcional ao PR, linkando o ADR quando houver. Sem nota de empilhamento nem rodapé de ferramenta.

## Escrita

Commits, PRs, comentários e docs em português. Direto, sem preâmbulo. Sem comentário que repete o código, sem docstring em função trivial.

## Stack

- Python 3.12, uv, FastAPI, uvicorn, pydantic-settings, SQLAlchemy 2 + Alembic, Postgres.
- PyTorch com CUDA e o pacote oficial do modelo escolhido; versão do modelo fixada por revisão/hash.
- boto3 (S3), SDK `mcp`, prometheus-client, logging estruturado em JSON com `request_id`.
- ffmpeg/PyAV só para codificação (Opus, MP3, μ-law), com licença conferida.
- mypy strict + plugin pydantic; ruff (E, F, I, UP, B, SIM); pytest + pytest-asyncio; testcontainers para Postgres.
- Docker com imagem CUDA; compose de dev com Postgres e MinIO.
- Plugin do LiveKit na mesma linguagem do agente atual (ver `docs/questoes-abertas.md`, questão 1).

## Regras críticas

- Segredos (chave da ElevenLabs, tokens, credenciais S3) só por ambiente; nunca no repositório, nunca em log.
- Tokens de cliente guardados como hash.
- Clonagem de voz só com registro em `voice_consent` (ADR-0007). Não remover marca d'água de nenhum modelo.
- Áudio de referência cifrado em repouso; áudio de lote com expiração no bucket.
- O caminho crítico do streaming não faz I/O de banco nem de rede além do motor; medição vai por fila em memória e é gravada fora do caminho.
- Toda mudança no motor ou na normalização roda a tabela de regressão (`tests/normalize/casos.yaml` e `bench/frases.yaml`).
