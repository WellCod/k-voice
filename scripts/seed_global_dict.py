"""Popula o dicionário global de pronúncia com entradas pt-BR.

Uso:
    uv run python scripts/seed_global_dict.py --token kv_... [--base-url http://localhost:8003]

Entradas já presentes são ignoradas (API retorna 409 ou entrada duplicada);
o script continua sem interromper.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

# (termo, expansão, is_regex)
ENTRADAS: list[tuple[str, str, bool]] = [
    # ── Siglas financeiras / bancárias ─────────────────────────────────────
    ("TED", "tê ê dê", False),
    ("DOC", "dê ô cê", False),
    ("CDB", "cê dê bê", False),
    ("LCI", "ele cê i", False),
    ("LCA", "ele cê á", False),
    ("CRI", "cê erre i", False),
    ("CRA", "cê erre á", False),
    ("CDC", "cê dê cê", False),
    ("IOF", "i ô efe", False),
    ("CDI", "cê dê i", False),
    ("SELIC", "selic", False),
    ("IPVA", "i pê vê á", False),
    ("IPTU", "i pê tê u", False),
    ("INSS", "i ene esse esse", False),
    ("FGTS", "fê gê tê esse", False),
    ("PGBL", "pê gê bê ele", False),
    ("VGBL", "vê gê bê ele", False),
    # ── Tecnologia / marcas ─────────────────────────────────────────────────
    ("PC", "pê cê", False),
    ("CPU", "cê pê u", False),
    ("GPU", "gê pê u", False),
    ("SSD", "esse esse dê", False),
    ("HD", "agá dê", False),
    ("USB", "u esse bê", False),
    ("HDMI", "agá dê eme i", False),
    ("RAM", "rã", False),
    ("ROM", "rôm", False),
    ("SDK", "esse dê cá", False),
    ("API", "a pê i", False),
    ("URL", "u erre ele", False),
    ("HTTP", "agá tê tê pê", False),
    ("HTTPS", "agá tê tê pê esse", False),
    ("SSL", "esse esse ele", False),
    ("TLS", "tê ele esse", False),
    ("PDF", "pê dê efe", False),
    ("JPG", "jota pê gê", False),
    ("PNG", "pê ene gê", False),
    ("MP3", "eme pê três", False),
    ("MP4", "eme pê quatro", False),
    ("IA", "i á", False),
    ("AI", "a i", False),
    # ── Termos em inglês com pronúncia específica ────────────────────────────
    ("WhatsApp", "uats ap", False),
    ("YouTube", "iúti iubi", False),
    ("TikTok", "tique toque", False),
    ("LinkedIn", "linquidin", False),
    ("Netflix", "Nétiflix", False),
    ("iPhone", "aifone", False),
    ("iPad", "aipade", False),
    ("Bluetooth", "blutuf", False),
    ("podcast", "pódqueste", False),
    ("streaming", "estrimingue", False),
    ("selfie", "selfi", False),
    ("hashtag", "áshtegue", False),
    ("download", "daonloud", False),
    ("upload", "aploud", False),
    ("backup", "béquiap", False),
    ("online", "onlaine", False),
    ("offline", "oflaine", False),
    ("feedback", "fídbéque", False),
    ("website", "uébsaite", False),
    ("software", "sóftuer", False),
    ("hardware", "árduer", False),
    ("startup", "estárt ap", False),
    ("cashback", "quéshbéque", False),
    ("voucher", "vâucher", False),
    ("checkout", "chécáute", False),
    ("score", "escôre", False),
    ("stories", "estóris", False),
    ("story", "estori", False),
    ("smartphone", "esmartefone", False),
    ("tablet", "téblete", False),
    ("notebook", "nótibuk", False),
    ("live", "laive", False),
    ("default", "difôlte", False),
    ("benchmark", "bénchmárque", False),
    ("sprint", "esprinte", False),
    ("scrum", "escrum", False),
    ("deploy", "deplói", False),
    ("framework", "freimuórque", False),
    ("router", "rrúter", False),
    ("firewall", "fáierual", False),
    ("dashboard", "dáshborde", False),
    ("login", "lógin", False),
    ("logout", "logáute", False),
    # ── Pronúncia de marcas / nomes próprios ─────────────────────────────────
    ("Nubank", "Núbank", False),
    ("Itaú", "Itaú", False),
    ("Bradesco", "Bradesco", False),
    ("Santander", "Santânder", False),
    ("Caixa", "Caixa", False),
    ("Klubi", "Klubi", False),
    # ── Unidades e medidas ────────────────────────────────────────────────────
    ("km/h", "quilômetros por hora", False),
    ("m/s", "metros por segundo", False),
    ("kWh", "quilouate-hora", False),
    # ── Expressões de fintech / crédito ──────────────────────────────────────
    ("fintech", "fintéque", False),
    ("fintechs", "fintéques", False),
    ("PIX", "pix", False),
    ("Pix", "pix", False),
    # ── Abreviações não cobertas pelo pré-processamento ──────────────────────
    ("p/", "para ", False),
    ("c/", "com ", False),
    ("s/", "sem ", False),
    ("nº", "número ", False),
    ("Nº", "número ", False),
    # ── Regex: telefone com 0800 ───────────────────────────────────────────────
    (r"\b0800\b", "zero oitocentos", True),
]


def post(base_url: str, token: str, entry: tuple[str, str, bool]) -> str:
    term, expansion, is_regex = entry
    payload = json.dumps({"term": term, "expansion": expansion, "is_regex": is_regex}).encode()
    req = urllib.request.Request(
        f"{base_url}/admin/pronunciation",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return "ok"
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:120]
        return f"skip ({e.code}): {body}"
    except Exception as e:
        return f"err: {e}"


def main() -> None:
    p = argparse.ArgumentParser(description="Seed global pronunciation dictionary")
    p.add_argument("--token", required=True, help="API token com escopo admin")
    p.add_argument("--base-url", default="http://localhost:8003")
    args = p.parse_args()

    ok = skip = err = 0
    for entry in ENTRADAS:
        result = post(args.base_url, args.token, entry)
        if result == "ok":
            ok += 1
            print(f"  ✓ {entry[0]}")
        elif result.startswith("skip"):
            skip += 1
            print(f"  ~ {entry[0]} — {result}")
        else:
            err += 1
            print(f"  ✗ {entry[0]} — {result}")

    print(f"\n{ok} adicionadas, {skip} ignoradas, {err} erros.")


if __name__ == "__main__":
    main()
