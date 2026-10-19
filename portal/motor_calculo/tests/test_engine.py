"""
Testes de rv/engine.py — foco no mapeamento loja -> regional (aba Lojas /
config.LOJA_REGIONAL) usado para consolidar DMA e faturamento por regional.

Este é o mecanismo que resolve o bug relatado pelo usuário: uma loja sem
NINGUÉM alocado no momento (reforma, troca de gestão etc. — ex: Canoas)
sumia dos totais da regional, obrigando a criar um colaborador fictício só
pra "existir" no cálculo. Ver docstring de rv/engine.py::_merge_coral.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from rv import engine


def _colab_base():
    return pd.DataFrame([
        {"matricula": 1, "unidade": "SAO10", "regional": "SUL", "grupo_calculo": "atendente", "dias_trabalhados": 30},
        {"matricula": 3, "unidade": "SUL_HQ", "regional": "SUL", "grupo_calculo": "regional", "dias_trabalhados": 30},
    ])


def _coral_df():
    # login1 (loja SAO10, com colaborador na folha) e login2 (loja CAN01,
    # SEM ninguém alocado na folha no momento).
    return pd.DataFrame([
        {"login_coral": "login1", "dma": 40.0, "dma_valor": 400.0, "dma_dias": 10.0,
         "faturamento_realizado": 5000.0, "unidade": "SAO10"},
        {"login_coral": "login2", "dma": 20.0, "dma_valor": 100.0, "dma_dias": 5.0,
         "faturamento_realizado": 0.0, "unidade": "CAN01"},
    ])


def _coral_por_loja_df():
    return pd.DataFrame([
        {"unidade": "SAO10", "fat_realizado_loja": 5000.0},
        {"unidade": "CAN01", "fat_realizado_loja": 3000.0},
    ])


def _meta_df():
    return pd.DataFrame([{"login_coral": "login1", "unidade": "SAO10", "meta_faturamento": 4000.0}])


def _mapeamento_df():
    return pd.DataFrame([{"login_coral": "login1", "matricula": 1}])


class TestConsolidacaoRegional(unittest.TestCase):
    def test_loja_sem_colaborador_na_folha_continua_contando_na_regional(self):
        """Com CAN01 cadastrada na aba Lojas (LOJA_REGIONAL), seu DMA e
        faturamento entram na consolidação da regional SUL mesmo sem
        nenhum colaborador lotado lá no momento."""
        with patch.object(engine, "LOJA_REGIONAL", {"SAO10": "SUL", "CAN01": "SUL"}), \
             patch.object(engine, "METAS_FATURAMENTO_REGIONAL", {"2026-06": {"SUL": 20000.0}}):
            resultado = engine._merge_coral(
                _colab_base(), _coral_df(), _coral_por_loja_df(), _meta_df(), _mapeamento_df(),
                "2026-06",
            )

        linha_regional = resultado.loc[resultado["matricula"] == 3].iloc[0]

        # DMA regional = (400+100) / (10+5) = 33.33... — só bateria 40.0 se
        # CAN01 (sem gente na folha) tivesse ficado de fora da soma.
        self.assertAlmostEqual(linha_regional["dma_regional"], 500.0 / 15.0, places=4)
        # Faturamento regional inclui os 3000 de CAN01 (5000 + 3000).
        self.assertAlmostEqual(linha_regional["fat_realizado_regional"], 8000.0)

    def test_loja_nao_cadastrada_em_lojas_e_sem_colaborador_desaparece_da_regional(self):
        """Sem CAN01 na aba Lojas E sem ninguém alocado lá, a regional não
        tem como saber a quem atribuir aquela loja — comportamento antigo,
        documentado aqui para deixar explícito o motivo de cadastrar toda
        loja ativa na aba Lojas (ver pendência: loja Canoas)."""
        with patch.object(engine, "LOJA_REGIONAL", {"SAO10": "SUL"}), \
             patch.object(engine, "METAS_FATURAMENTO_REGIONAL", {"2026-06": {"SUL": 20000.0}}):
            resultado = engine._merge_coral(
                _colab_base(), _coral_df(), _coral_por_loja_df(), _meta_df(), _mapeamento_df(),
                "2026-06",
            )

        linha_regional = resultado.loc[resultado["matricula"] == 3].iloc[0]
        # Só SAO10 é reconhecida — CAN01 fica de fora por falta de mapeamento.
        self.assertAlmostEqual(linha_regional["dma_regional"], 40.0)
        self.assertAlmostEqual(linha_regional["fat_realizado_regional"], 5000.0)

    def test_meta_de_faturamento_regional_ausente_cancela_o_calculo(self):
        with patch.object(engine, "LOJA_REGIONAL", {"SAO10": "SUL", "CAN01": "SUL"}), \
             patch.object(engine, "METAS_FATURAMENTO_REGIONAL", {}):
            with self.assertRaises(KeyError):
                engine._merge_coral(
                    _colab_base(), _coral_df(), _coral_por_loja_df(), _meta_df(), _mapeamento_df(),
                    "2026-06",
                )


def _cenario_loja(dias_b=15, com_meta_do_gestor=False, com_login_sem_mapeamento=False):
    """Loja SAO10: A (30 dias, meta 4000, vendeu 5000), B (meta 4000, vendeu nada) e um gestor."""
    colab = pd.DataFrame([
        {"matricula": 1, "unidade": "SAO10", "regional": "SUL", "grupo_calculo": "atendente", "dias_trabalhados": 30},
        {"matricula": 2, "unidade": "SAO10", "regional": "SUL", "grupo_calculo": "atendente", "dias_trabalhados": dias_b},
        {"matricula": 3, "unidade": "SAO10", "regional": "SUL", "grupo_calculo": "gestor", "dias_trabalhados": 30},
    ])
    coral = pd.DataFrame([
        {"login_coral": "l1", "dma": 40.0, "dma_valor": 400.0, "dma_dias": 10.0,
         "faturamento_realizado": 5000.0, "unidade": "SAO10"},
    ])
    por_loja = pd.DataFrame([{"unidade": "SAO10", "fat_realizado_loja": 5000.0}])
    metas = [
        {"login_coral": "l1", "unidade": "SAO10", "meta_faturamento": 4000.0},
        {"login_coral": "l2", "unidade": "SAO10", "meta_faturamento": 4000.0},
    ]
    mapa = [{"login_coral": "l1", "matricula": 1}, {"login_coral": "l2", "matricula": 2}]
    if com_meta_do_gestor:
        metas.append({"login_coral": "lg", "unidade": "SAO10", "meta_faturamento": 9000.0})
        mapa.append({"login_coral": "lg", "matricula": 3})
    if com_login_sem_mapeamento:
        metas.append({"login_coral": "lx", "unidade": "SAO10", "meta_faturamento": 3000.0})
    with patch.object(engine, "LOJA_REGIONAL", {"SAO10": "SUL"}),          patch.object(engine, "METAS_FATURAMENTO_REGIONAL", {}):
        return engine._merge_coral(colab, coral, por_loja, pd.DataFrame(metas), pd.DataFrame(mapa), "2026-09")


class TestMetaProporcionalAosDias(unittest.TestCase):
    def test_meta_individual_e_proporcional_aos_dias_trabalhados(self):
        r = _cenario_loja(dias_b=15)
        # B trabalhou 15 de 30 dias: meta de 4000 vira 2000. A (30 dias) segue com 4000.
        self.assertAlmostEqual(r.loc[r["matricula"] == 2, "meta_faturamento"].iloc[0], 2000.0)
        self.assertAlmostEqual(r.loc[r["matricula"] == 1, "meta_faturamento"].iloc[0], 4000.0)

    def test_meta_da_loja_soma_as_metas_proporcionais(self):
        r = _cenario_loja(dias_b=15)
        gestor = r.loc[r["matricula"] == 3].iloc[0]
        self.assertAlmostEqual(gestor["fat_meta_unidade"], 4000.0 + 2000.0)
        self.assertAlmostEqual(gestor["fat_realizado_unidade"] / gestor["fat_meta_unidade"], 5000.0 / 6000.0)

    def test_quem_tem_meta_e_nao_vendeu_nada_continua_na_meta_da_loja(self):
        """Regressão: a loja da meta vinha da venda, então B (sem venda) sumia da meta da loja e o
        atingimento dela ficava inflado (125% em vez de 62,5% com 5000 vendidos e meta de 8000)."""
        r = _cenario_loja(dias_b=30)
        gestor = r.loc[r["matricula"] == 3].iloc[0]
        self.assertAlmostEqual(gestor["fat_meta_unidade"], 8000.0)
        self.assertAlmostEqual(gestor["fat_realizado_unidade"] / gestor["fat_meta_unidade"], 0.625)

    def test_meta_individual_de_gestor_nao_entra_na_meta_da_loja(self):
        r = _cenario_loja(dias_b=30, com_meta_do_gestor=True)
        gestor = r.loc[r["matricula"] == 3].iloc[0]
        self.assertAlmostEqual(gestor["fat_meta_unidade"], 8000.0)

    def test_login_fora_da_lista_de_logins_entra_com_a_meta_cheia(self):
        r = _cenario_loja(dias_b=30, com_login_sem_mapeamento=True)
        gestor = r.loc[r["matricula"] == 3].iloc[0]
        self.assertAlmostEqual(gestor["fat_meta_unidade"], 8000.0 + 3000.0)

    def test_dias_acima_de_30_nao_aumentam_a_meta(self):
        r = _cenario_loja(dias_b=31)
        self.assertAlmostEqual(r.loc[r["matricula"] == 2, "meta_faturamento"].iloc[0], 4000.0)


if __name__ == "__main__":
    unittest.main()
