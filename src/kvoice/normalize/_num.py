"""Conversão de números para palavras em pt-BR."""

from __future__ import annotations

_UNIDADES = [
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
_DEZENAS = [
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
_CENTENAS = [
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
_CENTENAS_FEMININAS = ["", "cento", *(centena.replace("tos", "tas") for centena in _CENTENAS[2:])]
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


def _unidade(unidade: int, fem: bool) -> str:
    # Só "um" e "dois" têm forma feminina; de três em diante a palavra é a mesma.
    if fem and unidade in (1, 2):
        return "uma" if unidade == 1 else "duas"
    return _UNIDADES[unidade]


def _grupo(numero: int, fem: bool = False) -> str:
    """Converte 1–999 em palavras."""
    if numero < 20:
        return _unidade(numero, fem)
    if numero < 100:
        dezenas, unidades = divmod(numero, 10)
        return _DEZENAS[dezenas] + (" e " + _unidade(unidades, fem) if unidades else "")
    centenas, resto = divmod(numero, 100)
    # 100 redondo é "cem"; com resto vira "cento e ...".
    if resto == 0 and centenas == 1:
        base = "cem"
    else:
        base = (_CENTENAS_FEMININAS if fem else _CENTENAS)[centenas]
    return base + (" e " + _grupo(resto, fem) if resto else "")


def _conector(resto: int) -> str:
    """Conector entre a classe maior e o resto: "mil e cem", mas "mil duzentos e trinta".

    O "e" entra quando o resto é menor que cem ou é centena redonda.
    """
    return " e " if resto < 100 or resto % 100 == 0 else " "


def _positivo(numero: int, fem: bool = False) -> str:
    """Converte 1 até 999.999.999.999 em palavras."""
    # Feminino ("duas mil e duzentas pessoas") vale até os milhares; milhão e bilhão
    # são substantivos masculinos ("dois milhões de pessoas").
    if numero < 1_000:
        return _grupo(numero, fem)
    if numero < 1_000_000:
        milhares, resto = divmod(numero, 1_000)
        base = "mil" if milhares == 1 else _grupo(milhares, fem) + " mil"
        if not resto:
            return base
        return base + _conector(resto) + _positivo(resto, fem)
    if numero < 1_000_000_000:
        milhoes, resto = divmod(numero, 1_000_000)
        base = _grupo(milhoes) + (" milhão" if milhoes == 1 else " milhões")
        if not resto:
            return base
        return base + _conector(resto) + _positivo(resto, fem)
    bilhoes, resto = divmod(numero, 1_000_000_000)
    base = _grupo(bilhoes) + (" bilhão" if bilhoes == 1 else " bilhões")
    if not resto:
        return base
    # Depois de bilhão vale a mesma regra do conector, mas só com resto abaixo de um
    # milhão: "um bilhão e dois mil", porém "um bilhão dois milhões".
    conector = " e " if resto < 1_000_000 and (resto < 100 or resto % 100 == 0) else " "
    return base + conector + _positivo(resto, fem)


_MAIOR_POR_EXTENSO = 999_999_999_999


def numero_para_palavras(n: int, fem: bool = False) -> str:
    """Número inteiro por extenso; `fem` concorda com substantivo feminino até os milhares."""
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
    """Lê só os dígitos de `s`, um a um: "12-3" → "um dois três"."""
    return " ".join(DIGITOS[int(caractere)] for caractere in s if caractere.isdigit())
