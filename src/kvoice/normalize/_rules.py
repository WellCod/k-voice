"""Regras de normalização de texto pt-BR."""

from __future__ import annotations

import re

from kvoice.normalize._num import MESES, digitos_separados, numero_para_palavras

_LETRAS: dict[str, str] = {
    "A": "á",
    "B": "bê",
    "C": "cê",
    "D": "dê",
    "E": "ê",
    "F": "efe",
    "G": "gê",
    "H": "agá",
    "I": "i",
    "J": "jota",
    "K": "cá",
    "L": "ele",
    "M": "eme",
    "N": "ene",
    "O": "ô",
    "P": "pê",
    "Q": "quê",
    "R": "erre",
    "S": "esse",
    "T": "tê",
    "U": "u",
    "V": "vê",
    "W": "dáblio",
    "X": "xis",
    "Y": "ípsilon",
    "Z": "zê",
}

_ORD_M = [
    "",
    "primeiro",
    "segundo",
    "terceiro",
    "quarto",
    "quinto",
    "sexto",
    "sétimo",
    "oitavo",
    "nono",
    "décimo",
]
_ORD_F = [
    "",
    "primeira",
    "segunda",
    "terceira",
    "quarta",
    "quinta",
    "sexta",
    "sétima",
    "oitava",
    "nona",
    "décima",
]

# Siglas pronunciadas como palavras completas em pt-BR, não soletradas
_PALAVRAS_NATIVAS: dict[str, str] = {
    "PIX": "pix",
    "TV": "tevê",
    "LED": "led",
    "APP": "app",
    "WIFI": "uai fai",
}

# Patterns (ordem importa: mais específico primeiro)
_RE_CELSIUS = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*°C\b")
_RE_MOEDA = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*),(\d{2})")
_RE_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
_RE_CPF = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")
_RE_CEP = re.compile(r"\b(\d{5})-(\d{3})\b")
_RE_TELEFONE = re.compile(r"\((\d{2})\)\s*(\d{4,5})-(\d{4})")
_RE_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_RE_HORA = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_RE_PORCENTAGEM = re.compile(r"\b(\d+)(?:,(\d+))?\s*%")
_RE_DECIMAL = re.compile(r"\b(\d+),(\d{1,4})\b")
_RE_ORDINAL = re.compile(r"\b(\d+)([ºª°])")
_RE_ACRONIMO = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ]{2,6})\b")
_RE_CARDINAL = re.compile(r"\b\d+\b")
_RE_SAFE = re.compile(r"(?<=[.!?])\s+")


def _celsius(m: re.Match[str]) -> str:
    val = m.group(1).replace(",", ".")
    if "." in val:
        inteiro, dec = val.split(".", 1)
        dec_palavras = numero_para_palavras(int(dec))
        return f"{numero_para_palavras(int(inteiro))} vírgula {dec_palavras} graus Celsius"
    return f"{numero_para_palavras(int(val))} graus Celsius"


def _moeda(m: re.Match[str]) -> str:
    reais = int(m.group(1).replace(".", ""))
    cents = int(m.group(2))
    partes: list[str] = []
    if reais:
        valor = numero_para_palavras(reais)
        # "de" separa "milhão"/"bilhão" do substantivo
        sep = " de " if reais >= 1_000_000 else " "
        partes.append(valor + sep + ("real" if reais == 1 else "reais"))
    if cents:
        partes.append(numero_para_palavras(cents) + (" centavo" if cents == 1 else " centavos"))
    return " e ".join(partes) if partes else "zero reais"


def _cnpj(m: re.Match[str]) -> str:
    g = m.groups()
    return (
        f"{digitos_separados(g[0])}, {digitos_separados(g[1])}, "
        f"{digitos_separados(g[2])}, {digitos_separados(g[3])}, {digitos_separados(g[4])}"
    )


def _cpf(m: re.Match[str]) -> str:
    g = m.groups()
    return (
        f"{digitos_separados(g[0])}, {digitos_separados(g[1])}, "
        f"{digitos_separados(g[2])}, {digitos_separados(g[3])}"
    )


def _cep(m: re.Match[str]) -> str:
    return f"{digitos_separados(m.group(1))}, {digitos_separados(m.group(2))}"


def _telefone(m: re.Match[str]) -> str:
    ddd = numero_para_palavras(int(m.group(1)))
    p1 = digitos_separados(m.group(2))
    p2 = digitos_separados(m.group(3))
    return f"{ddd}, {p1}, {p2}"


def _data(m: re.Match[str]) -> str:
    d = int(m.group(1))
    mes = int(m.group(2))
    ano_str = m.group(3)
    if not (1 <= mes <= 12):
        return m.group(0)
    ano = int(ano_str)
    return f"{numero_para_palavras(d)} de {MESES[mes]} de {numero_para_palavras(ano)}"


def _hora(m: re.Match[str]) -> str:
    h = int(m.group(1))
    mi = int(m.group(2))
    base = "uma hora" if h == 1 else f"{numero_para_palavras(h)} horas"
    if mi == 0:
        return base
    return base + f" e {numero_para_palavras(mi)} minuto{'s' if mi != 1 else ''}"


def _porcentagem(m: re.Match[str]) -> str:
    inteiro = numero_para_palavras(int(m.group(1)))
    if m.group(2):
        dec = numero_para_palavras(int(m.group(2)))
        return f"{inteiro} vírgula {dec} por cento"
    return f"{inteiro} por cento"


def _decimal(m: re.Match[str]) -> str:
    inteiro = numero_para_palavras(int(m.group(1)))
    dec = numero_para_palavras(int(m.group(2)))
    return f"{inteiro} vírgula {dec}"


def _ordinal(m: re.Match[str]) -> str:
    n = int(m.group(1))
    fem = m.group(2) == "ª"
    tab = _ORD_F if fem else _ORD_M
    if 1 <= n < len(tab):
        return tab[n]
    return numero_para_palavras(n) + ("ª" if fem else "º")


def _acronimo(m: re.Match[str]) -> str:
    return " ".join(_LETRAS.get(c, c) for c in m.group(0))


def _cardinal(m: re.Match[str]) -> str:
    return numero_para_palavras(int(m.group(0)))


def normalize(text: str, dict_: dict[str, str] | None = None) -> str:
    if dict_:
        for termo, expansao in dict_.items():
            text = text.replace(termo, expansao)
    text = _RE_CELSIUS.sub(_celsius, text)
    text = _RE_MOEDA.sub(_moeda, text)
    text = _RE_CNPJ.sub(_cnpj, text)
    text = _RE_CPF.sub(_cpf, text)
    text = _RE_CEP.sub(_cep, text)
    text = _RE_TELEFONE.sub(_telefone, text)
    text = _RE_DATA.sub(_data, text)
    text = _RE_HORA.sub(_hora, text)
    text = _RE_PORCENTAGEM.sub(_porcentagem, text)
    text = _RE_DECIMAL.sub(_decimal, text)
    text = _RE_ORDINAL.sub(_ordinal, text)
    for sigla, forma in _PALAVRAS_NATIVAS.items():
        text = re.sub(rf"\b{re.escape(sigla)}\b", forma, text)
    text = _RE_ACRONIMO.sub(_acronimo, text)
    text = _RE_CARDINAL.sub(_cardinal, text)
    return text


def normalize_incremental(text: str, dict_: dict[str, str] | None = None) -> tuple[str, str]:
    """Retorna (pronto, pendente). Pendente aguarda mais texto para não quebrar padrões."""
    last: re.Match[str] | None = None
    for m in _RE_SAFE.finditer(text):
        last = m
    if last is None:
        return "", text
    pos = last.end()
    return normalize(text[:pos].rstrip(), dict_), text[pos:]
