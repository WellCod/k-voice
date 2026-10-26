# ADR-0001 — Serviço próprio, sem fork do VoiceStudio

- Estado: aceito
- Data: 2026-10-26

## Contexto

O VoiceStudio (github.com/debpalash/VoiceStudio) foi avaliado como base. Achados, conferidos no código em 2026-10-26 (v0.5.7):

- Licença AGPL-3.0: oferecer uma versão modificada pela rede obriga a publicar o código. Licença comercial é paga à parte.
- O modelo padrão (k2-fsa/OmniVoice) tem pesos CC-BY-NC. Nenhum modelo do inventário do projeto (`backend/config/model_licenses.json`) está liberado para uso comercial.
- Não há streaming real: o MCP não faz streaming e a rota compatível com OpenAI gera o áudio inteiro antes de fatiar (`backend/api/routers/openai_compat.py`).
- O MCP não tem autenticação e foi feito para loopback.
- É um app desktop (Electron) com dublagem, ditado, audiolivro e app móvel; a parte útil aqui é uma fração pequena.

## Decisão

Escrever um serviço próprio e enxuto. O VoiceStudio serve só de referência de ideias (motor como plugin, inventário de licenças, formato das tools MCP), sem copiar código.

## Consequências

- Sem obrigação AGPL.
- Mais código próprio, mas só o que o produto usa.
- Nenhuma dependência do ritmo de mudança do projeto (centenas de commits por mês).
