"""Regras de normalização de texto pt-BR."""

from __future__ import annotations

import re
from collections.abc import Callable

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
_RE_URL = re.compile(
    r"https?://\S+|www\.\S+"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|gov|edu|io|app|br)\b(?:/\S*)?",
    re.IGNORECASE,
)
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_RE_PONTUACAO_FINAL = re.compile(r"[.,;:!?)]+$")
_RE_RETICENCIAS = re.compile(r"\.{3,}|…")
_RE_PONTO_REPETIDO = re.compile(r"[!?]{2,}")
_SEPARADORES_ENDERECO = {".": "ponto", "/": "barra", "@": "arroba", "_": "underline", "-": "hífen"}
_PARTES_ENDERECO = {"www": "dáblio dáblio dáblio", "br": "bê erre"}
# Unidade colada ou separada do número: "5km", "500 ml", "1,5L". Singular quando o
# número é 1. "m" fica de fora (metro ou minuto) e "h" fica com as regras de hora.
_UNIDADES: dict[str, tuple[str, str]] = {
    "km/h": ("quilômetro por hora", "quilômetros por hora"),
    "km": ("quilômetro", "quilômetros"),
    "kg": ("quilo", "quilos"),
    "mg": ("miligrama", "miligramas"),
    "g": ("grama", "gramas"),
    "ml": ("mililitro", "mililitros"),
    "l": ("litro", "litros"),
    "cm": ("centímetro", "centímetros"),
    "mm": ("milímetro", "milímetros"),
    "min": ("minuto", "minutos"),
}
_RE_UNIDADE = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(km/h|km|kg|mg|g|ml|l|cm|mm|min)\b(?!/)", re.IGNORECASE
)
_RE_HORA_MIN = re.compile(r"\b(\d{1,2})h(\d{2})min\b")
_RE_DIMENSAO = re.compile(r"(?<![\w.,])(\d+)x(\d+)\b")
_RE_VEZES = re.compile(r"(?<![\w.,])(\d+)x\b", re.IGNORECASE)

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
    ("\ufe0f", ""),  # seletor de variação de emoji (❤️)
    ("\u200d", ""),  # zero-width joiner (emoji composto)
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
    (re.compile(r"\bApto\b\.?", re.IGNORECASE), "apartamento"),
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
    # Médico / saúde
    (re.compile(r"\bmcg\b"), "microgramas"),
    (re.compile(r"\bkcal\b", re.IGNORECASE), "quilocalorias"),
    (re.compile(r"\bbpm\b", re.IGNORECASE), "batimentos por minuto"),
    (re.compile(r"\bmmHg\b"), "milímetros de mercúrio"),
    # Agrário / imóveis
    (re.compile(r"\bha\b"), "hectares"),
    # Expressões comuns
    (re.compile(r"\bp\.\s*ex\.", re.IGNORECASE), "por exemplo"),
    (re.compile(r"\betc\.", re.IGNORECASE), "et cetera"),
    (re.compile(r"\bpágs?\.", re.IGNORECASE), "página"),
    (re.compile(r"\bvol\.", re.IGNORECASE), "volume"),
    (re.compile(r"\bvs?\.", re.IGNORECASE), "versus"),
    (re.compile(r"\bcf\.", re.IGNORECASE), "conforme"),
    (re.compile(r"\bapud\b", re.IGNORECASE), "apude"),
    (re.compile(r"\b[Nn]\.?[°º]\.?\s*"), "número "),
]

# Anglicismos com leitura pt-BR esperada (mais específico/longo antes)
_ANGLICISMOS: list[tuple[re.Pattern[str], str]] = [
    # ── Plataformas e redes sociais ─────────────────────────────────────────────
    (re.compile(r"\bWhatsApp\b"), "uats ap"),
    (re.compile(r"\bYouTube\b"), "iúti iubi"),
    (re.compile(r"\bTikTok\b", re.IGNORECASE), "tique toque"),
    (re.compile(r"\bLinkedIn\b", re.IGNORECASE), "linquidin"),
    (re.compile(r"\bInstagram\b", re.IGNORECASE), "instágrãm"),
    (re.compile(r"\bFacebook\b", re.IGNORECASE), "feisbuque"),
    (re.compile(r"\bTwitter\b", re.IGNORECASE), "tuíter"),
    (re.compile(r"\bSpotify\b", re.IGNORECASE), "espotifái"),
    (re.compile(r"\bNetflix\b", re.IGNORECASE), "Nétiflix"),
    (re.compile(r"\bAmazon\b", re.IGNORECASE), "âmazon"),
    (re.compile(r"\bUber\b", re.IGNORECASE), "iúber"),
    (re.compile(r"\biFood\b", re.IGNORECASE), "aifúde"),
    (re.compile(r"\bRappi\b", re.IGNORECASE), "rápi"),
    (re.compile(r"\bAirbnb\b", re.IGNORECASE), "êr bê êne bê"),
    (re.compile(r"\bPayPal\b", re.IGNORECASE), "pêipol"),
    # ── Dispositivos e marcas de tech ───────────────────────────────────────────
    (re.compile(r"\biPhone\b"), "aifone"),
    (re.compile(r"\biPad\b"), "aipade"),
    (re.compile(r"\biMac\b"), "aimaque"),
    (re.compile(r"\bAirPods\b", re.IGNORECASE), "êr pods"),
    (re.compile(r"\bBluetooth\b", re.IGNORECASE), "blutuf"),
    (re.compile(r"\bsmartphone\b", re.IGNORECASE), "esmartefone"),
    (re.compile(r"\btablet\b", re.IGNORECASE), "téblete"),
    (re.compile(r"\bnotebook\b", re.IGNORECASE), "nótibuk"),
    (re.compile(r"\bsmarttv\b", re.IGNORECASE), "esmart tê vê"),
    (re.compile(r"\bsmart\s+tv\b", re.IGNORECASE), "esmart tê vê"),
    (re.compile(r"\bpixel\b", re.IGNORECASE), "píxel"),
    # ── Termos de software / desenvolvimento ────────────────────────────────────
    (re.compile(r"\bsoftware\b", re.IGNORECASE), "sóftuer"),
    (re.compile(r"\bhardware\b", re.IGNORECASE), "árduer"),
    (re.compile(r"\bframework\b", re.IGNORECASE), "freimuórque"),
    (re.compile(r"\bdashboard\b", re.IGNORECASE), "dáshborde"),
    (re.compile(r"\bfirewall\b", re.IGNORECASE), "fáierual"),
    (re.compile(r"\brouter\b", re.IGNORECASE), "rrúter"),
    (re.compile(r"\bbenchmark\b", re.IGNORECASE), "bénchmárque"),
    (re.compile(r"\bdeployment\b", re.IGNORECASE), "deplóimento"),
    (re.compile(r"\bdeploy\b", re.IGNORECASE), "deplói"),
    (re.compile(r"\bstackoverflow\b", re.IGNORECASE), "estac ovérflou"),
    (re.compile(r"\bgithub\b", re.IGNORECASE), "guithabe"),
    (re.compile(r"\bdebug\b", re.IGNORECASE), "dibague"),
    (re.compile(r"\bbackend\b", re.IGNORECASE), "béquênde"),
    (re.compile(r"\bfrontend\b", re.IGNORECASE), "frôntênde"),
    (re.compile(r"\bwebsite\b", re.IGNORECASE), "uébsaite"),
    (re.compile(r"\bwebhook\b", re.IGNORECASE), "uébugue"),
    (re.compile(r"\btoken\b", re.IGNORECASE), "tóquen"),
    (re.compile(r"\bcache\b", re.IGNORECASE), "cáche"),
    (re.compile(r"\bcluster\b", re.IGNORECASE), "clúster"),
    (re.compile(r"\bserver\b", re.IGNORECASE), "sérver"),
    (re.compile(r"\bcheckout\b", re.IGNORECASE), "chécáute"),
    (re.compile(r"\blogin\b", re.IGNORECASE), "lógin"),
    (re.compile(r"\blogout\b", re.IGNORECASE), "logáute"),
    (re.compile(r"\bupdate\b", re.IGNORECASE), "apidéite"),
    (re.compile(r"\bupgrade\b", re.IGNORECASE), "apgréide"),
    (re.compile(r"\bbackup\b", re.IGNORECASE), "béquiap"),
    (re.compile(r"\bdownload\b", re.IGNORECASE), "daonloud"),
    (re.compile(r"\bupload\b", re.IGNORECASE), "aploud"),
    (re.compile(r"\bonline\b", re.IGNORECASE), "onlaine"),
    (re.compile(r"\boffline\b", re.IGNORECASE), "oflaine"),
    (re.compile(r"\bspam\b", re.IGNORECASE), "espam"),
    # ── Metodologias ágeis ──────────────────────────────────────────────────────
    (re.compile(r"\bsprint\b", re.IGNORECASE), "esprinte"),
    (re.compile(r"\bscrum\b", re.IGNORECASE), "escrum"),
    (re.compile(r"\bkanban\b", re.IGNORECASE), "canban"),
    (re.compile(r"\bstandup\b", re.IGNORECASE), "estândup"),
    (re.compile(r"\bstand-up\b", re.IGNORECASE), "estândup"),
    # ── Negócios / finanças ─────────────────────────────────────────────────────
    (re.compile(r"\bstartup\b", re.IGNORECASE), "estárt ap"),
    (re.compile(r"\bcashback\b", re.IGNORECASE), "quéshbéque"),
    (re.compile(r"\bvoucher\b", re.IGNORECASE), "vâucher"),
    (re.compile(r"\bscore\b", re.IGNORECASE), "escôre"),
    (re.compile(r"\bfintech\b", re.IGNORECASE), "fintéque"),
    (re.compile(r"\binsight\b", re.IGNORECASE), "ínsaite"),
    (re.compile(r"\bhighlight\b", re.IGNORECASE), "áilait"),
    (re.compile(r"\bbriefing\b", re.IGNORECASE), "brífingue"),
    (re.compile(r"\bmeeting\b", re.IGNORECASE), "mítingue"),
    (re.compile(r"\bleasing\b", re.IGNORECASE), "lízingue"),
    (re.compile(r"\bcoupon\b", re.IGNORECASE), "cupom"),
    (re.compile(r"\bcupom\b", re.IGNORECASE), "cupom"),
    (re.compile(r"\bprime\b", re.IGNORECASE), "praime"),
    (re.compile(r"\bhype\b", re.IGNORECASE), "haipe"),
    # ── Redes e conteúdo ────────────────────────────────────────────────────────
    (re.compile(r"\bpodcast\b", re.IGNORECASE), "pódqueste"),
    (re.compile(r"\bstreaming\b", re.IGNORECASE), "estrimingue"),
    (re.compile(r"\bselfie\b", re.IGNORECASE), "selfi"),
    (re.compile(r"\bhashtag\b", re.IGNORECASE), "áshtegue"),
    (re.compile(r"\bstories\b", re.IGNORECASE), "estóris"),
    (re.compile(r"\bstory\b", re.IGNORECASE), "estori"),
    (re.compile(r"\breels\b", re.IGNORECASE), "riils"),
    (re.compile(r"\blive\b"), "laive"),
    (re.compile(r"\btrailer\b", re.IGNORECASE), "tréiler"),
    (re.compile(r"\bteaser\b", re.IGNORECASE), "tízer"),
    (re.compile(r"\bspoiler\b", re.IGNORECASE), "espóiler"),
    (re.compile(r"\binfluencer\b", re.IGNORECASE), "influênser"),
    (re.compile(r"\bcreator\b", re.IGNORECASE), "criêitor"),
    (re.compile(r"\bfake\s+news\b", re.IGNORECASE), "feique niuze"),
    (re.compile(r"\bfake\b", re.IGNORECASE), "feique"),
    # ── Termos do cotidiano ─────────────────────────────────────────────────────
    (re.compile(r"\bfeedback\b", re.IGNORECASE), "fídbéque"),
    (re.compile(r"\bshopping\b", re.IGNORECASE), "xópin"),
    (re.compile(r"\bdefault\b", re.IGNORECASE), "difôlte"),
    (re.compile(r"\bstress\b", re.IGNORECASE), "estresse"),
    (re.compile(r"\bworkout\b", re.IGNORECASE), "uórquaute"),
    (re.compile(r"\bcoach\b", re.IGNORECASE), "cóche"),
    (re.compile(r"\bcooking\b", re.IGNORECASE), "cúquin"),
    (re.compile(r"\bsurfing\b", re.IGNORECASE), "sérfin"),
    (re.compile(r"\bsushi\b", re.IGNORECASE), "súchi"),
    (re.compile(r"\bdiesel\b", re.IGNORECASE), "dízel"),
    (re.compile(r"\blaser\b", re.IGNORECASE), "léizer"),
    # ── Atendimento, comércio e trabalho ────────────────────────────────────────
    (re.compile(r"\be-?mails?\b", re.IGNORECASE), "imeio"),
    (re.compile(r"\bsites?\b", re.IGNORECASE), "sáite"),
    (re.compile(r"\blinks?\b", re.IGNORECASE), "línqui"),
    (re.compile(r"\bchat\b", re.IGNORECASE), "chét"),
    (re.compile(r"\bchatbot\b", re.IGNORECASE), "chét bót"),
    (re.compile(r"\bdelivery\b", re.IGNORECASE), "delíveri"),
    (re.compile(r"\bhome\s+office\b", re.IGNORECASE), "rôme ófis"),
    (re.compile(r"\bcall\s+center\b", re.IGNORECASE), "cól sênter"),
    (re.compile(r"\bcall\b", re.IGNORECASE), "cól"),
    (re.compile(r"\bhelp\s*desk\b", re.IGNORECASE), "rélpi désqui"),
    (re.compile(r"\bdeadline\b", re.IGNORECASE), "dédlaine"),
    (re.compile(r"\bfollow-?up\b", re.IGNORECASE), "fólou ápi"),
    (re.compile(r"\bcheck-?in\b", re.IGNORECASE), "chéquin"),
    (re.compile(r"\bcheck-out\b", re.IGNORECASE), "chécáute"),
    (re.compile(r"\btickets?\b", re.IGNORECASE), "tíquete"),
    (re.compile(r"\bblack\s+friday\b", re.IGNORECASE), "bléque fráidei"),
    (re.compile(r"\bcyber\s+monday\b", re.IGNORECASE), "sáiber mândei"),
    (re.compile(r"\boutlet\b", re.IGNORECASE), "áutlet"),
    (re.compile(r"\bpremium\b", re.IGNORECASE), "prêmium"),
    (re.compile(r"\bgift\s+cards?\b", re.IGNORECASE), "guífti cárd"),
    (re.compile(r"\be-?commerce\b", re.IGNORECASE), "i cómerci"),
    (re.compile(r"\bmarketplace\b", re.IGNORECASE), "márquet plêice"),
    (re.compile(r"\bmarketing\b", re.IGNORECASE), "márquetin"),
    (re.compile(r"\blayout\b", re.IGNORECASE), "lêiaut"),
    (re.compile(r"\bdesign\b", re.IGNORECASE), "dizáin"),
    (re.compile(r"\bdesigner\b", re.IGNORECASE), "dizáiner"),
    (re.compile(r"\bfreelancer\b", re.IGNORECASE), "frilâncer"),
    (re.compile(r"\bjob\b", re.IGNORECASE), "djóbi"),
    (re.compile(r"\bbudget\b", re.IGNORECASE), "bâdjet"),
    (re.compile(r"\btarget\b", re.IGNORECASE), "tárguet"),
    (re.compile(r"\bleads?\b", re.IGNORECASE), "líd"),
    (re.compile(r"\branking\b", re.IGNORECASE), "rânquin"),
    (re.compile(r"\bknow-how\b", re.IGNORECASE), "nôu ráu"),
    (re.compile(r"\bQR\s*code\b", re.IGNORECASE), "quê erre côdi"),
    (re.compile(r"\bsmartwatch\b", re.IGNORECASE), "esmárti uótch"),
    (re.compile(r"\bheadsets?\b", re.IGNORECASE), "rédséti"),
    (re.compile(r"\bheadphones?\b", re.IGNORECASE), "réd fóne"),
    (re.compile(r"\bpen\s*drive\b", re.IGNORECASE), "pên dráive"),
    (re.compile(r"\bmouse\b", re.IGNORECASE), "máuse"),
    (re.compile(r"\bplayer\b", re.IGNORECASE), "plêier"),
    (re.compile(r"\bgames?\b", re.IGNORECASE), "guêime"),
    (re.compile(r"\bcloud\b", re.IGNORECASE), "cláud"),
    (re.compile(r"\bdata\s+center\b", re.IGNORECASE), "dêita sênter"),
    (re.compile(r"\bprint\b", re.IGNORECASE), "prínti"),
    # ── Marcas e serviços ───────────────────────────────────────────────────────
    (re.compile(r"\bGoogle\b", re.IGNORECASE), "gúgol"),
    (re.compile(r"\bGmail\b", re.IGNORECASE), "gê meio"),
    (re.compile(r"\bOutlook\b", re.IGNORECASE), "áutluk"),
    (re.compile(r"\bMicrosoft\b", re.IGNORECASE), "máicrossoft"),
    (re.compile(r"\bWindows\b", re.IGNORECASE), "uíndous"),
    (re.compile(r"\bAndroid\b", re.IGNORECASE), "andróid"),
    (re.compile(r"\bApple\b", re.IGNORECASE), "épou"),
    (re.compile(r"\bSamsung\b", re.IGNORECASE), "sâmsung"),
    (re.compile(r"\bShopee\b", re.IGNORECASE), "xópi"),
    (re.compile(r"\bShein\b", re.IGNORECASE), "xiín"),
    (re.compile(r"\bAliExpress\b", re.IGNORECASE), "áli espréss"),
    (re.compile(r"\bNubank\b", re.IGNORECASE), "nu bânqui"),
    (re.compile(r"\bPicPay\b", re.IGNORECASE), "píqui pêi"),
    (re.compile(r"\bMastercard\b", re.IGNORECASE), "máster cárd"),
    (re.compile(r"\bBooking\b", re.IGNORECASE), "búquin"),
    (re.compile(r"\bZoom\b"), "zum"),
    (re.compile(r"\bTeams\b"), "tíms"),
    (re.compile(r"\bSkype\b", re.IGNORECASE), "scáipe"),
    (re.compile(r"\bWaze\b", re.IGNORECASE), "uêize"),
    (re.compile(r"\bKwai\b", re.IGNORECASE), "cuái"),
    (re.compile(r"\bTwitch\b", re.IGNORECASE), "tuítch"),
    (re.compile(r"\bDiscord\b", re.IGNORECASE), "díscord"),
    (re.compile(r"\bGympass\b", re.IGNORECASE), "djím péss"),
    (re.compile(r"\bLoggi\b", re.IGNORECASE), "lógui"),
    # ── Pronúncia não óbvia ─────────────────────────────────────────────────────
    (re.compile(r"\bpok[eé]bola\b", re.IGNORECASE), "poquébola"),
    (re.compile(r"\bPokémon\b", re.IGNORECASE), "Pokêmon"),
    (re.compile(r"\bPikachu\b", re.IGNORECASE), "Picachú"),
    (re.compile(r"\bDisney\b", re.IGNORECASE), "Dízni"),
    (re.compile(r"\bMarvel\b", re.IGNORECASE), "Márvel"),
    (re.compile(r"\bNike\b", re.IGNORECASE), "Náiqui"),
    (re.compile(r"\bAdidas\b", re.IGNORECASE), "Adídas"),
    (re.compile(r"\bHyundai\b", re.IGNORECASE), "Rindai"),
    (re.compile(r"\bXiaomi\b", re.IGNORECASE), "Chiaomi"),
    (re.compile(r"\bHuawei\b", re.IGNORECASE), "Ruaréi"),
    # ── Palavras portuguesas com QU+vogal em que o U é pronunciado ──────────────
    # Após a reforma ortográfica de 1990 o trema foi suprimido (tranqüila → tranquila)
    # mas a pronúncia do U permanece; sem correção o modelo lê como /ki/ em vez de /kwi/.
    (re.compile(r"\btranquilamente\b", re.IGNORECASE), "trancuilamente"),
    (re.compile(r"\btranquilidade\b", re.IGNORECASE), "trancuilidade"),
    (re.compile(r"\btranquilizar\b", re.IGNORECASE), "trancuilizar"),
    (re.compile(r"\btranquilas\b", re.IGNORECASE), "trancuilas"),
    (re.compile(r"\btranquilo\b", re.IGNORECASE), "trancuilo"),
    (re.compile(r"\btranquila\b", re.IGNORECASE), "trancuila"),
    (re.compile(r"\bfrequentemente\b", re.IGNORECASE), "frecuentemente"),
    (re.compile(r"\bfrequentes\b", re.IGNORECASE), "frecuentes"),
    (re.compile(r"\bfrequência\b", re.IGNORECASE), "frecuência"),
    (re.compile(r"\bfrequente\b", re.IGNORECASE), "frecuente"),
    (re.compile(r"\bconsequentemente\b", re.IGNORECASE), "consecuentemente"),
    (re.compile(r"\bconsequências\b", re.IGNORECASE), "consecuências"),
    (re.compile(r"\bconsequência\b", re.IGNORECASE), "consecuência"),
    (re.compile(r"\bconsequentes\b", re.IGNORECASE), "consecuentes"),
    (re.compile(r"\bconsequente\b", re.IGNORECASE), "consecuente"),
    (re.compile(r"\bsubsequentes\b", re.IGNORECASE), "subsecuentes"),
    (re.compile(r"\bsubsequente\b", re.IGNORECASE), "subsecuente"),
    (re.compile(r"\badequadamente\b", re.IGNORECASE), "adecuadamente"),
    (re.compile(r"\binadequados\b", re.IGNORECASE), "inadecuados"),
    (re.compile(r"\binadequado\b", re.IGNORECASE), "inadecuado"),
    (re.compile(r"\badequados\b", re.IGNORECASE), "adecuados"),
    (re.compile(r"\badequada\b", re.IGNORECASE), "adecuada"),
    (re.compile(r"\badequado\b", re.IGNORECASE), "adecuado"),
]


def _ler_endereco(endereco: str) -> str:
    """URL ou e-mail por extenso: "site.com.br" → "site ponto com ponto bê erre"."""
    endereco = re.sub(r"^https?://", "", endereco, flags=re.IGNORECASE)
    endereco = re.split(r"[?#]", endereco)[0].rstrip("/")
    palavras: list[str] = []
    for parte in re.split(r"([./@_-])", endereco.lower()):
        if not parte:
            continue
        palavras.append(_SEPARADORES_ENDERECO.get(parte) or _PARTES_ENDERECO.get(parte, parte))
    return " ".join(palavras)


def _endereco(m: re.Match[str]) -> str:
    bruto = m.group(0)
    final = _RE_PONTUACAO_FINAL.search(bruto)
    sufixo = final.group(0) if final else ""
    return _ler_endereco(bruto[: len(bruto) - len(sufixo)]) + sufixo


def _pontuacao_repetida(m: re.Match[str]) -> str:
    # "Sério?!" continua pergunta.
    return "?" if "?" in m.group(0) else "!"


def _unidade(m: re.Match[str]) -> str:
    if m.group(2) == "G":
        return m.group(0)  # 4G e 5G são rede de celular, não gramas
    numero = m.group(1)
    singular, plural = _UNIDADES[m.group(2).lower()]
    return f"{numero} {singular if numero == '1' else plural}"


def _preprocess(text: str) -> str:
    """Lê URLs e e-mails, remove emojis, normaliza tipografia e expande abreviações."""
    text = _RE_EMAIL.sub(_endereco, text)
    text = _RE_URL.sub(_endereco, text)
    text = _RE_EMOJI.sub(" ", text)
    for old, new in _TIPOGRAFICOS:
        text = text.replace(old, new)
    text = _RE_RETICENCIAS.sub(", ", text)
    text = _RE_PONTO_REPETIDO.sub(_pontuacao_repetida, text)
    text = _RE_HORA_MIN.sub(r"\1h\2", text)
    text = _RE_DIMENSAO.sub(r"\1 por \2", text)
    text = _RE_VEZES.sub(r"\1 vezes", text)
    text = _RE_UNIDADE.sub(_unidade, text)
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
    # ── Tecnologia ─────────────────────────────────────────────────────────────
    "PIX": "pix",
    "TV": "tevê",
    "LED": "led",
    "APP": "app",
    "WIFI": "uai fai",
    "IA": "i á",
    "AI": "a i",
    "API": "a pê i",
    "RAM": "rã",
    "ROM": "rôm",
    "URL": "u erre ele",
    "ERP": "é erre pê",
    "KPI": "cá pê i",
    "SLA": "esse ele á",
    # ── Financeiro / bancário ───────────────────────────────────────────────────
    "TED": "tê ê dê",
    "DOC": "dê ó cê",
    "IOF": "i ô efe",
    "IOT": "i ô tê",
    "CEF": "cê ê efe",
    "CDI": "cê dê i",
    "CDB": "cê dê bê",
    "LCI": "ele cê i",
    "LCA": "ele cê á",
    "CRI": "cê erre i",
    "CRA": "cê erre á",
    "CDC": "cê dê cê",
    "PGBL": "pê gê bê ele",
    "VGBL": "vê gê bê ele",
    "SELIC": "selic",
    "IPCA": "i pê cê á",
    # ── Impostos / previdência ──────────────────────────────────────────────────
    "INSS": "i ene esse esse",
    "FGTS": "fê gê tê esse",
    "IPVA": "i pê vê á",
    "IPTU": "i pê tê u",
    "IRPF": "i erre pê efe",
    "IRPJ": "i erre pê jota",
    "ISS": "i esse esse",
    "ICMS": "i cê eme esse",
    "IPI": "i pê i",
    # ── Órgãos e instituições ───────────────────────────────────────────────────
    "SUS": "esse u esse",
    "OAB": "ô á bê",
    "BNDES": "bê ene dê ê esse",
    "IBGE": "i bê gê ê",
    "AGU": "á gê u",
    "TCU": "tê cê u",
    "CGU": "cê gê u",
    "TSE": "tê esse ê",
    "TST": "tê esse tê",
    "STF": "esse tê efe",
    "STJ": "esse tê jota",
    "ONU": "ô ene u",
    "OMS": "ô eme esse",
    # ── Saúde ───────────────────────────────────────────────────────────────────
    "UTI": "u tê i",
    # ── Mídia / comunicação ─────────────────────────────────────────────────────
    "BBC": "bê bê cê",
    "CNN": "cê ene ene",
    "HBO": "agá bê ô",
    "ESPN": "i esse pê ene",
    "MTV": "eme tê vê",
    # ── Esportes ────────────────────────────────────────────────────────────────
    "UFC": "u efe cê",
    "NBA": "ene bê á",
    "NFL": "ene efe ele",
    "MLB": "eme ele bê",
    "NHL": "ene agá ele",
    # ── Universidades ───────────────────────────────────────────────────────────
    "USP": "u esse pê",
    "UNB": "u ene bê",
    "IME": "i eme ê",
    # ── Documentos ──────────────────────────────────────────────────────────────
    "CEP": "cê ê pê",
    "CPF": "cê pê efe",
    "RG": "erre gê",
    "CNH": "cê ene agá",
    "CNPJ": "cê ene pê jota",
    "CTPS": "cê tê pê esse",
    "DPVAT": "dê pê vê á tê",
    "NIS": "ene i esse",
    "CRLV": "cê erre ele vê",
    # ── Notas fiscais ───────────────────────────────────────────────────────────
    "NF-e": "nota fiscal eletrônica",
    "NFC-e": "nota fiscal de consumidor eletrônica",
    "NFS-e": "nota fiscal de serviço eletrônica",
    # ── Impostos e índices (com vogal: sem isto viravam palavra) ─────────────────
    "IR": "i erre",
    "IRRF": "i erre erre efe",
    "ITBI": "i tê bê i",
    "ITCMD": "i tê cê eme dê",
    "INPC": "i ene pê cê",
    "IGPM": "i gê pê eme",
    "IGP-M": "i gê pê eme",
    "CET": "cê ê tê",
    "TEF": "tê ê efe",
    "DI": "dê i",
    # ── Saúde ───────────────────────────────────────────────────────────────────
    "AVC": "á vê cê",
    "HIV": "agá i vê",
    "IST": "i esse tê",
    "IMC": "i eme cê",
    "ECG": "ê cê gê",
    "UBS": "u bê esse",
    "ANS": "á ene esse",
    # ── Governo, órgãos e lugares ───────────────────────────────────────────────
    "EUA": "ê u á",
    "UE": "u ê",
    "UF": "u efe",
    "OIT": "ô i tê",
    "OEA": "ô ê á",
    # ── Educação ────────────────────────────────────────────────────────────────
    "EAD": "ê á dê",
    # ── Tecnologia e telefonia ──────────────────────────────────────────────────
    "TI": "tê i",
    "UI": "u i",
    "UX": "u xis",
    "IOS": "ai ô esse",
    "SEO": "esse ê ó",
    "OK": "oquei",
    "FAQ": "efe á quê",
    "CEO": "ci i ôu",
    "CTO": "ci ti ôu",
    "CFO": "ci efe ôu",
    "2G": "dois gê",
    "3G": "três gê",
    "4G": "quatro gê",
    "5G": "cinco gê",
    "4K": "quatro cá",
    "8K": "oito cá",
    "MP3": "eme pê três",
    "MP4": "eme pê quatro",
    "USB-C": "u esse bê cê",
    "WI-FI": "uai fai",
    "OLX": "ô ele xis",
    # ── Automóveis ──────────────────────────────────────────────────────────────
    "SUV": "esse u vê",
    "ABS": "á bê esse",
}

# Siglas que também são palavras ou nomes ("eu ia", "ai", "o doc", "Ted"): só trocadas
# quando escritas em maiúscula. As demais valem em qualquer caixa ("pix", "cpf").
_SO_MAIUSCULA = frozenset(
    {
        "IA",
        "AI",
        "DOC",
        "TED",
        "SLA",
        "SUS",
        "RAM",
        "ROM",
        "IME",
        "LED",
        # "ir", "ti", "ui", "ué", "di", "uf" e "nis" também são palavras.
        "IR",
        "TI",
        "UI",
        "UE",
        "DI",
        "UF",
        "NIS",
        "ABS",
    }
)
_RE_PALAVRAS_NATIVAS = [
    (
        re.compile(rf"\b{re.escape(sigla)}\b", 0 if sigla in _SO_MAIUSCULA else re.IGNORECASE),
        forma,
    )
    for sigla, forma in _PALAVRAS_NATIVAS.items()
]

# Substantivos femininos que costumam vir depois de número na fala de atendimento:
# "duas parcelas", "vinte e uma horas", "duzentas pessoas".
_FEMININOS = frozenset(
    [
        "hora",
        "horas",
        "parcela",
        "parcelas",
        "vez",
        "vezes",
        "pessoa",
        "pessoas",
        "semana",
        "semanas",
        "unidade",
        "unidades",
        "prestação",
        "prestações",
        "mensalidade",
        "mensalidades",
        "fatura",
        "faturas",
        "opção",
        "opções",
        "noite",
        "noites",
        "diária",
        "diárias",
        "vaga",
        "vagas",
        "caixa",
        "caixas",
        "peça",
        "peças",
        "conta",
        "contas",
        "linha",
        "linhas",
        "criança",
        "crianças",
        "página",
        "páginas",
        "tentativa",
        "tentativas",
        "cópia",
        "cópias",
        "nota",
        "notas",
        "ocorrência",
        "ocorrências",
        "libra",
        "libras",
        "cota",
        "cotas",
        "etapa",
        "etapas",
        "loja",
        "lojas",
        "cidade",
        "cidades",
        "empresa",
        "empresas",
    ]
)
_RE_PALAVRA_SEGUINTE = re.compile(r"\s+(\w+)")


def _feminino_depois(m: re.Match[str]) -> bool:
    seguinte = _RE_PALAVRA_SEGUINTE.match(m.string, m.end())
    return seguinte is not None and seguinte.group(1).lower() in _FEMININOS


# ---------------------------------------------------------------------------
# Patterns (ordem importa: mais específico primeiro)
# ---------------------------------------------------------------------------

_RE_CELSIUS = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*°C\b")
# R$ 1.500,00 · R$ 1500 · R$ 10,5 · R$ 2 mil · R$ 1,5 milhão
_RE_MOEDA = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(?![\d.,]\d|\d)"
    r"(?:\s+(mil|milhão|milhões|bilhão|bilhões)\b)?"
)
# Decimal com ponto ("1.5", "10.50"): vira vírgula. Com até duas casas não colide com
# separador de milhar, IP nem versão de três partes.
_RE_DECIMAL_PONTO = re.compile(r"(?<![\d.,])(\d+)\.(\d{1,2})(?!\d|\.\d)")
_RE_VERSAO = re.compile(r"\b(versão|v)\s*(\d+)\.(\d+)\b", re.IGNORECASE)
_RE_DATA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_MES_ANO = re.compile(r"(?<![\d/])(\d{1,2})/(\d{4})\b")
# Intervalo com hífen: "7-10 dias", "10-20%", "8h-18h", "2020-2024". Telefone, CEP,
# CPF, CNPJ e data ISO já saíram antes.
_RE_INTERVALO = re.compile(
    r"(?<![\w.,/-])(\d+(?:,\d+)?)(%|h)?\s?-\s?(\d+(?:,\d+)?)(%|h)?(?![\w.,/-])"
)
_RE_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
_RE_CPF = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")
_RE_CEP = re.compile(r"\b(\d{5})-(\d{3})\b")
# Telefone: com ou sem parênteses e +55, separado ou colado. O DDD sai como número e
# o resto dígito a dígito. Sem DDD, só celular (9XXXX-XXXX) e os números de capitais
# (4002-8922): um fixo de 4+4 sem DDD não se separa de um intervalo como 2020-2024.
_RE_TELEFONE = re.compile(r"(\+55\s*)?\((\d{2})\)\s*(\d{4,5})[\s-]?(\d{4})(?!\d)")
_RE_TELEFONE_SEM_PARENTESES = re.compile(
    r"(?<![\d(])(\+55\s*)?(\d{2})[\s-](9\d{4}|[2-5]\d{3})[\s-]?(\d{4})(?![\d-])"
)
_RE_TELEFONE_COLADO = re.compile(r"(?<![\d+])(\+55\s*)?(\d{2})(9\d{4})(\d{4})(?!\d)")
_RE_TELEFONE_SEM_DDD = re.compile(r"(?<![\d-])(9\d{4}|300[2-9]|400[1-9])-(\d{4})(?![\d-])")
_RE_TELEFONE_0800 = re.compile(r"(?<!\d)0([3589])00[\s-]?(\d{3})[\s-]?(\d{4})(?!\d)")
_RE_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_RE_DATA_CURTA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)")
_RE_HORA_H = re.compile(r"\b(\d{1,2})h(\d{2})?\b")
_RE_HORA = re.compile(r"\b(\d{1,2}):(\d{2})h?\b")
_RE_PORCENTAGEM = re.compile(r"\b(\d+)(?:,(\d+))?\s*%")
_RE_DECIMAL = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{3})+|\d+),(\d{1,4})\b")
# Separador de milhar: 1.000, 2.008, 3.000.000.000. CPF e CNPJ já saíram antes;
# IP e versão (192.168.0.1, 1.2.3) não têm grupos de três depois do primeiro.
_RE_MILHAR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+)(?![\d.]|,\d)")
_RE_ORDINAL = re.compile(r"\b(\d+)([ºª°])")
_RE_ACRONIMO = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ]{2,20})\b")
_RE_CARDINAL = re.compile(r"\b\d+\b")
_MIN_DIGITOS_CODIGO = 10
_RE_SAFE = re.compile(r"(?<=[.!?])\s+")
# Ponto que não fecha frase: abreviação ("Sr.", "apto."), inicial ("José R.") e item
# de lista ("1."). Cortar ali partiria "O Sr. João" em duas falas e deixaria "Sr." cru.
_ABREVIACOES_COM_PONTO = frozenset(
    [
        "sr",
        "sra",
        "srta",
        "dr",
        "dra",
        "prof",
        "profa",
        "eng",
        "enga",
        "engº",
        "adv",
        "av",
        "apto",
        "bl",
        "art",
        "inc",
        "obs",
        "pág",
        "págs",
        "vol",
        "v",
        "vs",
        "cf",
        "nº",
        "n°",
        "n.º",
        "ltda",
        "cia",
        "s.a",
        "tel",
        "cel",
        "ex",
        "p.ex",
        "jd",
        "pq",
        "lt",
    ]
)
_RE_TOKEN_ANTES = re.compile(r"(\S+)\.$")

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
    casas = m.group(2) or ""
    multiplicador = m.group(3)
    if multiplicador:
        # "R$ 2 mil" → "dois mil reais"; "R$ 1,5 milhão" → "um vírgula cinco milhão de reais"
        valor = numero_para_palavras(reais)
        if casas:
            valor += " vírgula " + numero_para_palavras(int(casas))
        de = "" if multiplicador == "mil" else " de"
        return f"{valor} {multiplicador}{de} reais"
    # Um dígito depois da vírgula é dezena de centavos: R$ 10,5 = dez reais e cinquenta.
    cents = int(casas.ljust(2, "0")) if casas else 0
    partes: list[str] = []
    if reais:
        valor = numero_para_palavras(reais)
        sep = " de " if reais >= 1_000_000 else " "
        partes.append(valor + sep + ("real" if reais == 1 else "reais"))
    if cents:
        partes.append(numero_para_palavras(cents) + (" centavo" if cents == 1 else " centavos"))
    return " e ".join(partes) if partes else "zero reais"


def _versao(m: re.Match[str]) -> str:
    return f"{m.group(1)} {m.group(2)} ponto {m.group(3)}"


def _dia(d: int) -> str:
    return "primeiro" if d == 1 else numero_para_palavras(d)


def _data_iso(m: re.Match[str]) -> str:
    ano, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return m.group(0)
    return f"{_dia(dia)} de {MESES[mes]} de {numero_para_palavras(ano)}"


def _mes_ano(m: re.Match[str]) -> str:
    mes = int(m.group(1))
    if not 1 <= mes <= 12:
        return m.group(0)
    return f"{MESES[mes]} de {numero_para_palavras(int(m.group(2)))}"


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
    pais, ddd, p1, p2 = m.groups()
    falado = f"{numero_para_palavras(int(ddd))}, {digitos_separados(p1)}, {digitos_separados(p2)}"
    return f"mais cinquenta e cinco, {falado}" if pais else falado


def _telefone_sem_ddd(m: re.Match[str]) -> str:
    return f"{digitos_separados(m.group(1))}, {digitos_separados(m.group(2))}"


def _telefone_0800(m: re.Match[str]) -> str:
    prefixo = numero_para_palavras(int(m.group(1)) * 100)  # 0800 → "zero oitocentos"
    return f"zero {prefixo}, {digitos_separados(m.group(2))}, {digitos_separados(m.group(3))}"


def _data(m: re.Match[str]) -> str:
    d = int(m.group(1))
    mes = int(m.group(2))
    if not (1 <= mes <= 12):
        return m.group(0)
    ano = int(m.group(3))
    return f"{_dia(d)} de {MESES[mes]} de {numero_para_palavras(ano)}"


def _data_curta(m: re.Match[str]) -> str:
    d = int(m.group(1))
    mes = int(m.group(2))
    if 1 <= d <= 12 and mes > 12 and len(m.group(2)) == 2:
        # Validade de cartão: 12/25 → "dezembro de vinte e cinco"
        return f"{MESES[d]} de {numero_para_palavras(mes)}"
    if not (1 <= mes <= 12) or not (1 <= d <= 31):
        return m.group(0)
    return f"{_dia(d)} de {MESES[mes]}"


def _hora(m: re.Match[str]) -> str:
    h = int(m.group(1))
    mi = int(m.group(2))
    base = "uma hora" if h == 1 else f"{numero_para_palavras(h, fem=True)} horas"
    if mi == 0:
        return base
    return base + f" e {numero_para_palavras(mi)} minuto{'s' if mi != 1 else ''}"


def _hora_h(m: re.Match[str]) -> str:
    h = int(m.group(1))
    base = "uma hora" if h == 1 else f"{numero_para_palavras(h, fem=True)} horas"
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
    inteiro = numero_para_palavras(int(m.group(1).replace(".", "")))
    casas = m.group(2)
    # 0,05 é "zero vírgula zero cinco": os zeros à esquerda da parte decimal se falam
    zeros = len(casas) - len(casas.lstrip("0"))
    resto = casas[zeros:]
    dec = " ".join(["zero"] * zeros + ([numero_para_palavras(int(resto))] if resto else []))
    return f"{inteiro} vírgula {dec}"


def _milhar(m: re.Match[str]) -> str:
    return numero_para_palavras(int(m.group(1).replace(".", "")), fem=_feminino_depois(m))


def _ordinal(m: re.Match[str]) -> str:
    n = int(m.group(1))
    fem = m.group(2) == "ª"
    result = _ordinal_para_palavras(n, fem)
    if result:
        return result
    # Acima de 999: retorna apenas o cardinal (símbolo seria ilegível pelo TTS)
    return numero_para_palavras(n)


_VOGAIS_UPPER = frozenset("AEIOUÁÉÍÓÚÂÊÎÔÛÃÕ")


def _acronimo(m: re.Match[str]) -> str:
    palavra = m.group(0)
    # Qualquer vogal → palavra em caixa alta (ênfase), não sigla → minúscula.
    # Siglas com vogal que devem ser soletradas (TED, SUS, CDI…) já foram tratadas
    # por _PALAVRAS_NATIVAS antes desta etapa.
    # Siglas sem vogal (CPF, RG, STF, FGTS…) → soletra letra a letra.
    # Universidades e institutos federais (UFRJ, UFMG, UERJ, IFSP): têm vogal, mas
    # ninguém lê como palavra.
    if len(palavra) >= 3 and palavra[:2] in ("UF", "UE", "IF"):
        return " ".join(_LETRAS.get(c, c) for c in palavra)
    if any(c in _VOGAIS_UPPER for c in palavra):
        return palavra.lower()
    return " ".join(_LETRAS.get(c, c) for c in palavra)


def _cardinal(m: re.Match[str]) -> str:
    s = m.group(0)
    # Código ou número longo (protocolo, pedido) e número com zero à esquerda (007)
    # se falam dígito a dígito.
    if len(s) >= _MIN_DIGITOS_CODIGO or (len(s) > 1 and s[0] == "0"):
        return digitos_separados(s)
    return numero_para_palavras(int(s), fem=_feminino_depois(m))


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def normalize(text: str, dict_: dict[str, str] | None = None) -> str:
    text = _preprocess(text)
    if dict_:
        for termo, expansao in dict_.items():
            text = text.replace(termo, expansao)
    text = _RE_CELSIUS.sub(_celsius, text)
    text = _RE_VERSAO.sub(_versao, text)
    text = _RE_DECIMAL_PONTO.sub(r"\1,\2", text)
    text = _RE_MOEDA.sub(_moeda, text)
    text = _RE_CNPJ.sub(_cnpj, text)
    text = _RE_CPF.sub(_cpf, text)
    text = _RE_CEP.sub(_cep, text)
    text = _RE_DATA_ISO.sub(_data_iso, text)
    text = _RE_TELEFONE_0800.sub(_telefone_0800, text)
    text = _RE_TELEFONE.sub(_telefone, text)
    text = _RE_TELEFONE_SEM_PARENTESES.sub(_telefone, text)
    text = _RE_TELEFONE_COLADO.sub(_telefone, text)
    text = _RE_TELEFONE_SEM_DDD.sub(_telefone_sem_ddd, text)
    text = _RE_INTERVALO.sub(r"\1\2 a \3\4", text)
    text = _RE_DATA.sub(_data, text)
    text = _RE_MES_ANO.sub(_mes_ano, text)
    text = _RE_DATA_CURTA.sub(_data_curta, text)
    text = _RE_HORA.sub(_hora, text)
    text = _RE_HORA_H.sub(_hora_h, text)
    text = _RE_PORCENTAGEM.sub(_porcentagem, text)
    text = _RE_DECIMAL.sub(_decimal, text)
    text = _RE_MILHAR.sub(_milhar, text)
    text = _RE_ORDINAL.sub(_ordinal, text)
    for padrao, forma in _RE_PALAVRAS_NATIVAS:
        text = padrao.sub(forma, text)
    for pat, rep in _ANGLICISMOS:
        text = pat.sub(rep, text)
    text = _RE_ACRONIMO.sub(_acronimo, text)
    text = _RE_CARDINAL.sub(_cardinal, text)
    return text


def _fecha_frase(text: str, fim: int) -> bool:
    antes = _RE_TOKEN_ANTES.search(text, 0, fim)
    if antes is None:
        return True
    token = antes.group(1).lower()
    if token in _ABREVIACOES_COM_PONTO:
        return False
    # Inicial ("José R.") e item de lista ("1.") esperam mais texto: esperar à toa só
    # atrasa a fala, cortar errado a parte em duas.
    return not (token.isdigit() or (len(token) == 1 and token.isalpha()))


def normalize_incremental(
    text: str,
    dict_: dict[str, str] | None = None,
    pre: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """Retorna (pronto, pendente). Pendente aguarda mais texto para não quebrar padrões.

    `pre` recebe só as frases completas, antes da normalização (dicionário do cliente):
    um termo nunca é aplicado partido entre dois pedaços do LLM.
    """
    last: re.Match[str] | None = None
    for m in _RE_SAFE.finditer(text):
        if _fecha_frase(text, m.start()):
            last = m
    if last is None:
        return "", text
    pos = last.end()
    pronto = text[:pos].rstrip()
    if pre is not None:
        pronto = pre(pronto)
    return normalize(pronto, dict_), text[pos:]
