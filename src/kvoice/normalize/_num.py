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


def _grupo(n: int) -> str:
    """Converte 1–999 em palavras."""
    if n < 20:
        return _U[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _D[d] + (" e " + _U[u] if u else "")
    c, r = divmod(n, 100)
    base = "cem" if (r == 0 and c == 1) else _C[c]
    return base + (" e " + _grupo(r) if r else "")


def _positivo(n: int) -> str:
    if n < 1_000:
        return _grupo(n)
    if n < 1_000_000:
        k, r = divmod(n, 1_000)
        base = "mil" if k == 1 else _grupo(k) + " mil"
        if not r:
            return base
        e = " e " if r < 100 or r % 100 == 0 else " "
        return base + e + _positivo(r)
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        base = _grupo(m) + (" milhão" if m == 1 else " milhões")
        if not r:
            return base
        e = " e " if r < 100 or r % 100 == 0 else " "
        return base + e + _positivo(r)
    b, r = divmod(n, 1_000_000_000)
    base = _grupo(b) + (" bilhão" if b == 1 else " bilhões")
    if not r:
        return base
    e = " e " if r < 1_000_000 and (r < 100 or r % 100 == 0) else " "
    return base + e + _positivo(r)


def numero_para_palavras(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return "menos " + numero_para_palavras(-n)
    return _positivo(n)


def digitos_separados(s: str) -> str:
    return " ".join(DIGITOS[int(c)] for c in s if c.isdigit())
