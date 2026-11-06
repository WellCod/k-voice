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
