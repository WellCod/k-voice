"""Limites de texto e síntese em partes, comuns a lote, compat, MCP e streaming."""

from __future__ import annotations

import re

from kvoice.audio import pcm_duration_ms
from kvoice.engine.types import Audio, SynthOptions, TTSEngine, Voice

# Texto por pedido de lote, compat e MCP, e por fala no WebSocket.
MAX_CARACTERES = 10_000
# Uma fala do agente raramente passa de algumas frases; acima disto o pedaço é cortado
# antes de ir ao motor, para não segurar o lock com uma "frase" gigante.
MAX_CARACTERES_SEGMENTO = 600

# Preferência: dividir em ponto final para preservar o contexto de perguntas e exclamações.
_RE_FRASE_PONTO = re.compile(r"(?<=[.])\s+")
_RE_FRASE = re.compile(r"(?<=[.!?])\s+")
_RE_PAUSA = re.compile(r"[,;:]\s")
_SILENCIO_ENTRE_PARTES_S = 0.06


def cortar_em_pausa(texto: str, limite: int = MAX_CARACTERES_SEGMENTO) -> tuple[str, str]:
    """Corta `texto` em até `limite` caracteres: na última vírgula, ponto e vírgula ou
    dois-pontos; sem pausa, no último espaço; sem espaço, no próprio limite.

    Devolve (cabeça, resto). Cortar em espaço pode separar "R$" de "1.234"; a pausa
    vem antes justamente para evitar isso na maior parte dos textos.
    """
    if len(texto) <= limite:
        return texto, ""
    janela = texto[:limite]
    pausas = list(_RE_PAUSA.finditer(janela))
    if pausas:
        corte = pausas[-1].end()
    else:
        espaco = janela.rfind(" ")
        corte = espaco + 1 if espaco > 0 else limite
    return texto[:corte].rstrip(), texto[corte:].lstrip()


def dividir_sentencas(texto: str) -> list[str]:
    """Divide texto longo em partes de até MAX_CARACTERES_SEGMENTO, em fim de frase."""
    if len(texto) <= MAX_CARACTERES_SEGMENTO:
        return [texto]
    for regex in (_RE_FRASE_PONTO, _RE_FRASE):
        frases = regex.split(texto.strip())
        if len(frases) > 1:
            break
    partes: list[str] = []
    for frase in frases:
        # Frase sem pontuação maior que o segmento: corte por pausa ou palavra.
        while len(frase) > MAX_CARACTERES_SEGMENTO:
            cabeca, frase = cortar_em_pausa(frase)
            partes.append(cabeca)
        if frase:
            partes.append(frase)
    grupos: list[str] = []
    atual = ""
    for parte in partes:
        if not atual:
            atual = parte
        elif len(atual) + 1 + len(parte) <= MAX_CARACTERES_SEGMENTO:
            atual += " " + parte
        else:
            grupos.append(atual)
            atual = parte
    if atual:
        grupos.append(atual)
    return grupos or [texto]


async def sintetizar_em_partes(
    engine: TTSEngine, texto: str, voice: Voice, opts: SynthOptions
) -> Audio:
    """Sintetiza texto já normalizado, parte a parte, e junta com uma pausa curta."""
    partes = dividir_sentencas(texto)
    if len(partes) == 1:
        return await engine.synthesize(partes[0], voice, opts)
    pcm: list[bytes] = []
    ttfa_ms = 0.0
    for i, parte in enumerate(partes):
        seg = await engine.synthesize(parte, voice, opts)
        if i == 0:
            ttfa_ms = seg.ttfa_ms
        pcm.append(seg.data)
    silencio = b"\x00" * int(_SILENCIO_ENTRE_PARTES_S * engine.sample_rate) * 2
    junto = silencio.join(pcm)
    return Audio(
        data=junto,
        sample_rate=engine.sample_rate,
        duration_ms=pcm_duration_ms(junto, engine.sample_rate),
        ttfa_ms=ttfa_ms,
    )
