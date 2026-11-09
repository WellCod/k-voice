"""Conversão de números para palavras em pt-BR."""

from __future__ import annotations

_U = [
    "",
    "um",
    "dois",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
]
_D = [
    "",
    "",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
]
_C = [
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
]
_C_F = ["", "cento", *(c.replace("tos", "tas") for c in _C[2:])]
DIGITOS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]
MESES = [
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


def _unidade(u: int, fem: bool) -> str:
    if fem and u in (1, 2):
        return "uma" if u == 1 else "duas"
    return _U[u]


def _grupo(n: int, fem: bool = False) -> str:
    """Converte 1–999 em palavras."""
    if n < 20:
        return _unidade(n, fem)
    if n < 100:
        d, u = divmod(n, 10)
        return _D[d] + (" e " + _unidade(u, fem) if u else "")
    c, r = divmod(n, 100)
    base = "cem" if (r == 0 and c == 1) else (_C_F if fem else _C)[c]
    return base + (" e " + _grupo(r, fem) if r else "")


def _positivo(n: int, fem: bool = False) -> str:
    # Feminino ("duas mil e duzentas pessoas") vale até os milhares; milhão e bilhão
    # são substantivos masculinos ("dois milhões de pessoas").
    if n < 1_000:
        return _grupo(n, fem)
    if n < 1_000_000:
        k, r = divmod(n, 1_000)
        base = "mil" if k == 1 else _grupo(k, fem) + " mil"
        if not r:
            return base
        e = " e " if r < 100 or r % 100 == 0 else " "
        return base + e + _positivo(r, fem)
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        base = _grupo(m) + (" milhão" if m == 1 else " milhões")
        if not r:
            return base
        e = " e " if r < 100 or r % 100 == 0 else " "
        return base + e + _positivo(r, fem)
    b, r = divmod(n, 1_000_000_000)
    base = _grupo(b) + (" bilhão" if b == 1 else " bilhões")
    if not r:
        return base
    e = " e " if r < 1_000_000 and (r < 100 or r % 100 == 0) else " "
    return base + e + _positivo(r, fem)


_MAIOR_POR_EXTENSO = 999_999_999_999


def numero_para_palavras(n: int, fem: bool = False) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return "menos " + numero_para_palavras(-n, fem)
    if n > _MAIOR_POR_EXTENSO:
        # Acima dos bilhões não há nome que alguém fale; um código desse tamanho se lê
        # dígito a dígito (e o _grupo estouraria com o grupo de bilhões acima de 999).
        return digitos_separados(str(n))
    return _positivo(n, fem)


def digitos_separados(s: str) -> str:
    return " ".join(DIGITOS[int(c)] for c in s if c.isdigit())
