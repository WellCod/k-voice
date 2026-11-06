"""Funções de comparação do bench de pronúncia (sem ASR nem motor)."""

from bench.pronuncia import canonico, distancia, palavras_divergentes, taxa_erro


def test_canonico_iguala_numero_escrito_e_falado() -> None:
    assert canonico("R$ 10") == canonico("dez reais") == "dez reais"


def test_canonico_tira_acento_pontuacao_e_caixa() -> None:
    assert canonico("Olá! Tudo BEM?") == "ola tudo bem"


def test_canonico_aplica_a_normalizacao_do_servidor() -> None:
    # sigla sem vogal é soletrada pelo normalizador, nos dois lados da comparação
    assert canonico("O CPF") == canonico("o cê pê efe")


def test_distancia() -> None:
    assert distancia([], []) == 0
    assert distancia(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert distancia(["a", "b", "c"], ["a", "x", "c"]) == 1  # substituição
    assert distancia(["a", "b"], ["a", "b", "c"]) == 1  # inserção
    assert distancia(["a", "b", "c"], ["a", "c"]) == 1  # remoção
    assert distancia(list("casa"), list("asa")) == 1


def test_taxa_erro() -> None:
    assert taxa_erro(["a", "b", "c", "d"], ["a", "b", "x", "d"]) == 0.25
    assert taxa_erro([], []) == 0.0
    assert taxa_erro([], ["a"]) == 1.0
    assert taxa_erro(["a"], []) == 1.0


def test_palavras_divergentes_mostra_o_que_nao_foi_ouvido() -> None:
    ref = ["o", "pix", "cai", "na", "hora"]
    hip = ["o", "peixe", "cai", "na", "hora"]
    assert palavras_divergentes(ref, hip) == ["pix"]
    assert palavras_divergentes(ref, ref) == []


def test_canonico_le_sequencia_longa_digito_a_digito() -> None:
    # o ASR junta documentos numa sequência só; o normalizador não aguenta 13+ dígitos
    assert canonico("CNPJ 12345678000199").endswith(
        "um dois tres quatro cinco seis sete oito zero zero zero um nove nove"
    )


def test_canonico_compara_documento_pelos_digitos_e_nao_pelo_agrupamento() -> None:
    assert canonico("CPF 123.456.789-09") == canonico("CPF 123-456-789-09")
    assert canonico("(11) 3456-7890") == canonico("11-3456-7890")
    assert canonico("CEP 01310-100") == canonico("CEP 013-10100")
    assert canonico("CEP 01310-100").endswith("zero um tres um zero um zero zero")


def test_canonico_mantem_valor_e_data_como_palavras() -> None:
    assert canonico("R$ 1.234,50") == "mil duzentos e trinta e quatro reais e cinquenta centavos"
    assert "dezembro" in canonico("25/12/2026")
    assert canonico("em 2026") == "em dois mil e vinte e seis"


def test_canonico_telefone_fala_ddd_como_numero() -> None:
    assert canonico("(21) 99123-4567") == canonico("21991234567") == canonico("21-99123-4567")
    assert canonico("(21) 99123-4567").startswith("vinte e um nove nove um")


def test_canonico_cnpj_com_barra_e_numero_antes_de_virgula() -> None:
    assert canonico("CNPJ 12.345.678/0001-99") == canonico("CNPJ 12345678000199")
    assert canonico("ligue 0800 123 4567, é gratuito") == canonico(
        "ligue 0800-123-4567. É gratuito"
    )
    assert "dezembro" in canonico("em 25/12/2026, às 10h")
