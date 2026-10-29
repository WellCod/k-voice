"""Regras de normalização de texto pt-BR."""

from __future__ import annotations

import re

from kvoice.normalize._num import MESES, digitos_separados, numero_para_palavras

# ---------------------------------------------------------------------------
# Pré-processamento (antes da normalização de padrões)
# ---------------------------------------------------------------------------

_RE_EMOJI = re.compile(
    "[\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # símbolos e pictogramas
    "\U0001f680-\U0001f6ff"  # transporte e mapas
    "\U0001f1e0-\U0001f1ff"  # bandeiras
    "\U00002600-\U000027bf"  # símbolos Unicode miscelâneos
    "\U0001f900-\U0001f9ff"  # suplemento de símbolos expressivos
    "\U0001fa00-\U0001faff"  # símbolos e pictogramas estendidos A/B
    "]+",
    flags=re.UNICODE,
)
_RE_URL = re.compile(r"https?://\S+|www\.\S+")
_RE_RETICENCIAS = re.compile(r"\.{3,}|…")
_RE_PONTO_REPETIDO = re.compile(r"([!?]){2,}")

# Caracteres tipográficos que confundem o TTS
_TIPOGRAFICOS: list[tuple[str, str]] = [
    ("\u00a0", " "),  # espaço não-quebrável → espaço normal
    ("\u200b", ""),  # zero-width space → remove
    ("\u200c", ""),  # zero-width non-joiner → remove
    ("—", ", "),  # em-dash → pausa com vírgula
    ("–", " a "),  # en-dash → "de X a Y" (intervalos)
    ("\u2018", "'"),  # aspas simples esquerdas → apóstrofo padrão
    ("\u2019", "'"),  # aspas simples direitas → apóstrofo padrão
    ("\u201c", '"'),  # aspas duplas esquerdas
    ("\u201d", '"'),  # aspas duplas direitas
    ("×", " vezes "),
    ("÷", " dividido por "),
    ("≥", " maior ou igual a "),
    ("≤", " menor ou igual a "),
    ("≈", " aproximadamente "),
    ("±", " mais ou menos "),
    ("→", " "),
    ("←", " "),
    ("↑", " "),
    ("↓", " "),
    ("§", "parágrafo "),
]

# Abreviações: (padrão, expansão) — ordem importa (mais específico antes)
_ABREVIACOES: list[tuple[re.Pattern[str], str]] = [
    # Unidades compostas (antes das simples para não haver sobreposição parcial)
    (re.compile(r"\bkm/h\b", re.IGNORECASE), "quilômetros por hora"),
    (re.compile(r"\bkm/s\b", re.IGNORECASE), "quilômetros por segundo"),
    (re.compile(r"\bm/s\b"), "metros por segundo"),
    (re.compile(r"\bkWh\b"), "quilouate hora"),
    (re.compile(r"\bGHz\b"), "gigahertz"),
    (re.compile(r"\bMHz\b"), "megahertz"),
    (re.compile(r"\bkHz\b"), "quilohertz"),
    (re.compile(r"\bHz\b"), "hertz"),
    (re.compile(r"\bkW\b"), "quilouates"),
    (re.compile(r"\bMW\b"), "megauates"),
    (re.compile(r"\bkm[²2]\b"), "quilômetros quadrados"),
    (re.compile(r"\bcm[²2]\b"), "centímetros quadrados"),
    (re.compile(r"\bm[²2]\b"), "metros quadrados"),
    (re.compile(r"\bm[³3]\b"), "metros cúbicos"),
    (re.compile(r"\bcm[³3]\b"), "centímetros cúbicos"),
    # Unidades simples
    (re.compile(r"\bkm\b", re.IGNORECASE), "quilômetros"),
    (re.compile(r"\bkg\b", re.IGNORECASE), "quilogramas"),
    (re.compile(r"\bcm\b"), "centímetros"),
    (re.compile(r"\bmm\b"), "milímetros"),
    (re.compile(r"\bml\b"), "mililitros"),
    (re.compile(r"\bmg\b"), "miligramas"),
    # Tratamentos e profissões (mais específico antes)
    (re.compile(r"\bDra\.(?=\s)", re.IGNORECASE), "doutora"),
    (re.compile(r"\bDr\.(?=\s)", re.IGNORECASE), "doutor"),
    (re.compile(r"\bProfa\.(?=\s)", re.IGNORECASE), "professora"),
    (re.compile(r"\bProf\.(?=\s)", re.IGNORECASE), "professor"),
    (re.compile(r"\bSra\.(?=\s)", re.IGNORECASE), "senhora"),
    (re.compile(r"\bSr\.(?=\s)", re.IGNORECASE), "senhor"),
    (re.compile(r"\bEng[aº°]?\.(?=\s)", re.IGNORECASE), "engenheiro"),
    (re.compile(r"\bAdv\.(?=\s)", re.IGNORECASE), "advogado"),
    # Endereços
    (re.compile(r"\bAv\.(?=\s)", re.IGNORECASE), "avenida"),
    (re.compile(r"\bR\.(?=\s[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ])"), "rua"),
    (re.compile(r"\bApto\.?\b", re.IGNORECASE), "apartamento"),
    (re.compile(r"\bBl\.(?=\s)", re.IGNORECASE), "bloco"),
    # Jurídico / empresarial
    (re.compile(r"\bart\.(?=\s)", re.IGNORECASE), "artigo"),
    (re.compile(r"\binc\.(?=\s)", re.IGNORECASE), "inciso"),
    (re.compile(r"\bobs\.(?=[\s:])", re.IGNORECASE), "observação"),
    (re.compile(r"\bltda\.?\b", re.IGNORECASE), "limitada"),
    (re.compile(r"\bS\.?\s*A\.?\b"), "sociedade anônima"),
    (re.compile(r"\bcia\.?\b", re.IGNORECASE), "companhia"),
    (re.compile(r"\bEPP\b"), "empresa de pequeno porte"),
    (re.compile(r"\bMEI\b"), "microempreendedor individual"),
    (re.compile(r"\bME\b"), "microempresa"),
    # Expressões comuns
    (re.compile(r"\bp\.\s*ex\.", re.IGNORECASE), "por exemplo"),
    (re.compile(r"\betc\.", re.IGNORECASE), "et cetera"),
    (re.compile(r"\bpágs?\.", re.IGNORECASE), "página"),
    (re.compile(r"\bvol\.", re.IGNORECASE), "volume"),
    (re.compile(r"\bn[°º]\s*"), "número "),
]

# Anglicismos com leitura pt-BR esperada
_ANGLICISMOS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bWhatsApp\b"), "uats ap"),
    (re.compile(r"\bYouTube\b"), "iúti iubi"),
    (re.compile(r"\bTikTok\b", re.IGNORECASE), "tique toque"),
    (re.compile(r"\bLinkedIn\b", re.IGNORECASE), "linquidin"),
    (re.compile(r"\bNetflix\b", re.IGNORECASE), "Nétiflix"),
    (re.compile(r"\biPhone\b"), "aifone"),
    (re.compile(r"\biPad\b"), "aipade"),
    (re.compile(r"\bBluetooth\b", re.IGNORECASE), "blutuf"),
    (re.compile(r"\bpodcast\b", re.IGNORECASE), "pódqueste"),
    (re.compile(r"\bstreaming\b", re.IGNORECASE), "estrimingue"),
    (re.compile(r"\bselfie\b", re.IGNORECASE), "selfi"),
    (re.compile(r"\bhashtag\b", re.IGNORECASE), "áshtegue"),
    (re.compile(r"\bdownload\b", re.IGNORECASE), "daonloud"),
    (re.compile(r"\bupload\b", re.IGNORECASE), "aploud"),
    (re.compile(r"\bbackup\b", re.IGNORECASE), "béquiap"),
    (re.compile(r"\bonline\b", re.IGNORECASE), "onlaine"),
    (re.compile(r"\boffline\b", re.IGNORECASE), "oflaine"),
    (re.compile(r"\bfeedback\b", re.IGNORECASE), "fídbéque"),
    (re.compile(r"\bwebsite\b", re.IGNORECASE), "uébsaite"),
    (re.compile(r"\bsoftware\b", re.IGNORECASE), "sóftuer"),
    (re.compile(r"\bhardware\b", re.IGNORECASE), "árduer"),
    (re.compile(r"\bstartup\b", re.IGNORECASE), "estárt ap"),
    (re.compile(r"\bcashback\b", re.IGNORECASE), "quéshbéque"),
    (re.compile(r"\bvoucher\b", re.IGNORECASE), "vâucher"),
    (re.compile(r"\bcheckout\b", re.IGNORECASE), "chécáute"),
    (re.compile(r"\bscore\b", re.IGNORECASE), "escôre"),
    (re.compile(r"\bstories\b", re.IGNORECASE), "estóris"),
    (re.compile(r"\bstory\b", re.IGNORECASE), "estori"),
    (re.compile(r"\blive\b"), "laive"),
    (re.compile(r"\bsmartphone\b", re.IGNORECASE), "esmartefone"),
    (re.compile(r"\btablet\b", re.IGNORECASE), "téblete"),
    (re.compile(r"\bnotebook\b", re.IGNORECASE), "nótibuk"),
]


def _preprocess(text: str) -> str:
    """Remove URLs, emojis, normaliza caracteres tipográficos e expande abreviações."""
    text = _RE_URL.sub("", text)
    text = _RE_EMOJI.sub(" ", text)
    for old, new in _TIPOGRAFICOS:
        text = text.replace(old, new)
    text = _RE_RETICENCIAS.sub(", ", text)
    text = _RE_PONTO_REPETIDO.sub(r"\1", text)
    for pat, rep in _ABREVIACOES:
        text = pat.sub(rep, text)
    text = re.sub(r"  +", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Tabelas de letras e ordinais
# ---------------------------------------------------------------------------

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

_ORD_UNIT_M = [
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
]
_ORD_UNIT_F = [
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
]
_ORD_DEZ_M = [
    "",
    "",
    "vigésimo",
    "trigésimo",
    "quadragésimo",
    "quinquagésimo",
    "sexagésimo",
    "septuagésimo",
    "octogésimo",
    "nonagésimo",
]
_ORD_DEZ_F = [
    "",
    "",
    "vigésima",
    "trigésima",
    "quadragésima",
    "quinquagésima",
    "sexagésima",
    "septuagésima",
    "octogésima",
    "nonagésima",
]
_ORD_CEM_M = [
    "",
    "centésimo",
    "ducentésimo",
    "trecentésimo",
    "quadringentésimo",
    "quingentésimo",
    "sexcentésimo",
    "septingentésimo",
    "octingentésimo",
    "noningentésimo",
]
_ORD_CEM_F = [
    "",
    "centésima",
    "ducentésima",
    "trecentésima",
    "quadringentésima",
    "quingentésima",
    "sexcentésima",
    "septingentésima",
    "octingentésima",
    "noningentésima",
]


def _ordinal_para_palavras(n: int, fem: bool = False) -> str | None:
    """Converte n (1–999) em ordinal por extenso. Retorna None se fora do intervalo."""
    if not (1 <= n <= 999):
        return None
    unit = _ORD_UNIT_F if fem else _ORD_UNIT_M
    dez = _ORD_DEZ_F if fem else _ORD_DEZ_M
    cem = _ORD_CEM_F if fem else _ORD_CEM_M
    decimo = "décima" if fem else "décimo"
    partes: list[str] = []
    c, r = divmod(n, 100)
    if c:
        partes.append(cem[c])
    if r < 10:
        if r:
            partes.append(unit[r])
    elif r < 20:
        partes.append(decimo if r == 10 else f"{decimo} {unit[r - 10]}")
    else:
        d, u = divmod(r, 10)
        partes.append(dez[d])
        if u:
            partes.append(unit[u])
    return " ".join(partes)


# Siglas pronunciadas como palavras completas em pt-BR, não soletradas
_PALAVRAS_NATIVAS: dict[str, str] = {
    "PIX": "pix",
    "TV": "tevê",
    "LED": "led",
    "APP": "app",
    "WIFI": "uai fai",
}

# ---------------------------------------------------------------------------
# Patterns (ordem importa: mais específico primeiro)
# ---------------------------------------------------------------------------

_RE_CELSIUS = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*°C\b")
_RE_MOEDA = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*),(\d{2})")
_RE_MOEDA_INT = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*)\b")
_RE_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
_RE_CPF = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")
_RE_CEP = re.compile(r"\b(\d{5})-(\d{3})\b")
_RE_TELEFONE = re.compile(r"\((\d{2})\)\s*(\d{4,5})-(\d{4})")
_RE_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_RE_DATA_CURTA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)")
_RE_HORA_H = re.compile(r"\b(\d{1,2})h(\d{2})?\b")
_RE_HORA = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_RE_PORCENTAGEM = re.compile(r"\b(\d+)(?:,(\d+))?\s*%")
_RE_DECIMAL = re.compile(r"\b(\d+),(\d{1,4})\b")
_RE_ORDINAL = re.compile(r"\b(\d+)([ºª°])")
_RE_ACRONIMO = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ]{2,6})\b")
_RE_CARDINAL = re.compile(r"\b\d+\b")
_RE_SAFE = re.compile(r"(?<=[.!?])\s+")

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


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
        sep = " de " if reais >= 1_000_000 else " "
        partes.append(valor + sep + ("real" if reais == 1 else "reais"))
    if cents:
        partes.append(numero_para_palavras(cents) + (" centavo" if cents == 1 else " centavos"))
    return " e ".join(partes) if partes else "zero reais"


def _moeda_int(m: re.Match[str]) -> str:
    n = int(m.group(1).replace(".", ""))
    valor = numero_para_palavras(n)
    sep = " de " if n >= 1_000_000 else " "
    return valor + sep + ("real" if n == 1 else "reais")


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
    if not (1 <= mes <= 12):
        return m.group(0)
    ano = int(m.group(3))
    return f"{numero_para_palavras(d)} de {MESES[mes]} de {numero_para_palavras(ano)}"


def _data_curta(m: re.Match[str]) -> str:
    d = int(m.group(1))
    mes = int(m.group(2))
    if not (1 <= mes <= 12) or not (1 <= d <= 31):
        return m.group(0)
    return f"{numero_para_palavras(d)} de {MESES[mes]}"


def _hora(m: re.Match[str]) -> str:
    h = int(m.group(1))
    mi = int(m.group(2))
    base = "uma hora" if h == 1 else f"{numero_para_palavras(h)} horas"
    if mi == 0:
        return base
    return base + f" e {numero_para_palavras(mi)} minuto{'s' if mi != 1 else ''}"


def _hora_h(m: re.Match[str]) -> str:
    h = int(m.group(1))
    base = "uma hora" if h == 1 else f"{numero_para_palavras(h)} horas"
    mi_str = m.group(2)
    if mi_str:
        mi = int(mi_str)
        if mi:
            return base + f" e {numero_para_palavras(mi)} minuto{'s' if mi != 1 else ''}"
    return base


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
    result = _ordinal_para_palavras(n, fem)
    if result:
        return result
    # Acima de 999: retorna apenas o cardinal (símbolo seria ilegível pelo TTS)
    return numero_para_palavras(n)


def _acronimo(m: re.Match[str]) -> str:
    return " ".join(_LETRAS.get(c, c) for c in m.group(0))


def _cardinal(m: re.Match[str]) -> str:
    return numero_para_palavras(int(m.group(0)))


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def normalize(text: str, dict_: dict[str, str] | None = None) -> str:
    text = _preprocess(text)
    if dict_:
        for termo, expansao in dict_.items():
            text = text.replace(termo, expansao)
    text = _RE_CELSIUS.sub(_celsius, text)
    text = _RE_MOEDA.sub(_moeda, text)
    text = _RE_MOEDA_INT.sub(_moeda_int, text)
    text = _RE_CNPJ.sub(_cnpj, text)
    text = _RE_CPF.sub(_cpf, text)
    text = _RE_CEP.sub(_cep, text)
    text = _RE_TELEFONE.sub(_telefone, text)
    text = _RE_DATA.sub(_data, text)
    text = _RE_DATA_CURTA.sub(_data_curta, text)
    text = _RE_HORA_H.sub(_hora_h, text)
    text = _RE_HORA.sub(_hora, text)
    text = _RE_PORCENTAGEM.sub(_porcentagem, text)
    text = _RE_DECIMAL.sub(_decimal, text)
    text = _RE_ORDINAL.sub(_ordinal, text)
    for sigla, forma in _PALAVRAS_NATIVAS.items():
        text = re.sub(rf"\b{re.escape(sigla)}\b", forma, text, flags=re.IGNORECASE)
    for pat, rep in _ANGLICISMOS:
        text = pat.sub(rep, text)
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
