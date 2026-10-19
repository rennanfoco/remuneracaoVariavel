"""
Testes de rv/calculators/calculadora.py — o núcleo do cálculo de RV (faixas
de atingimento, metas mensais, dependência entre indicadores e regra
específica por loja).

REGRAS e METAS_MENSAIS são lidos de config.py (que por sua vez lê o
referencias.xlsx real) na hora do `import`, e importados por nome dentro de
calculadora.py (`from config import REGRAS, METAS_MENSAIS`) — por isso cada
teste troca esses dois nomes por um cenário controlado via mock.patch, em vez
de depender do conteúdo do referencias.xlsx real.
"""

import unittest
from unittest.mock import patch

from rv.calculators import calculadora


def _regra(faixas, direcao="maior", chave_meta=None, depende_indicador=None, depende_valor_min=None):
    return {
        None: {
            "direcao": direcao,
            "chave_meta": chave_meta,
            "depende_indicador": depende_indicador,
            "depende_valor_min": depende_valor_min,
            "faixas": faixas,
        }
    }


class TestAvaliarFaixaMaiorMelhor(unittest.TestCase):
    def setUp(self):
        faixas = [
            {"faixa": 1, "min": 40.0, "max": 59.99, "pct": 0.05},
            {"faixa": 2, "min": 60.0, "max": None, "pct": 0.10},
        ]
        self.regras = {"atendente": {"dma": _regra(faixas)}}

    def test_faixa_intermediaria(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 45.0}, "2026-06")
        self.assertEqual(res["detalhes"]["dma"]["faixa"], 1)
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.05)
        self.assertAlmostEqual(res["rv_base"], 50.0)

    def test_faixa_mais_alta_sem_teto(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 999.0}, "2026-06")
        self.assertEqual(res["detalhes"]["dma"]["faixa"], 2)
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.10)

    def test_valor_abaixo_da_faixa_minima_nao_pontua(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 10.0}, "2026-06")
        self.assertEqual(res["detalhes"]["dma"]["faixa"], 0)
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.0)
        self.assertAlmostEqual(res["rv_base"], 0.0)

    def test_fronteira_e_inclusiva_e_favorece_a_faixa_mais_alta(self):
        # 60.0 é o mínimo exato da faixa 2 — deve cair na faixa 2, não na 1,
        # mesmo a faixa 1 tendo max=59.99 (sem sobreposição real aqui, mas
        # comprova que o limite é fechado [min, max] dos dois lados).
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 60.0}, "2026-06")
        self.assertEqual(res["detalhes"]["dma"]["faixa"], 2)


class TestAvaliarFaixaMenorMelhor(unittest.TestCase):
    def setUp(self):
        # NONREV: menor é melhor. Faixa 2 (melhor) tem o teto mais baixo.
        faixas = [
            {"faixa": 1, "min": None, "max": 5.0, "pct": 0.02},
            {"faixa": 2, "min": None, "max": 2.0, "pct": 0.05},
        ]
        self.regras = {"lider_frota": {"nonrev": _regra(faixas, direcao="menor")}}

    def test_melhor_faixa_atingida(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("lider_frota", 500.0, {"nonrev": 1.5}, "2026-06")
        self.assertEqual(res["detalhes"]["nonrev"]["faixa"], 2)
        self.assertAlmostEqual(res["detalhes"]["nonrev"]["pct"], 0.05)

    def test_faixa_pior_ainda_dentro_do_limite(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("lider_frota", 500.0, {"nonrev": 3.5}, "2026-06")
        self.assertEqual(res["detalhes"]["nonrev"]["faixa"], 1)
        self.assertAlmostEqual(res["detalhes"]["nonrev"]["pct"], 0.02)

    def test_acima_do_maior_teto_nao_pontua(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("lider_frota", 500.0, {"nonrev": 6.0}, "2026-06")
        self.assertEqual(res["detalhes"]["nonrev"]["faixa"], 0)


class TestChaveMeta(unittest.TestCase):
    def setUp(self):
        # pct vem de Regras_Calculo, mas min/max de METAS_MENSAIS[competencia][chave].
        faixas = [{"faixa": 1, "min": None, "max": None, "pct": 0.03},
                  {"faixa": 2, "min": None, "max": None, "pct": 0.08}]
        self.regras = {"lider_frota": {"nps": _regra(faixas, chave_meta="nps_lider_frota")}}
        self.metas = {
            "2026-06": {
                "nps_lider_frota": [
                    {"faixa": 1, "min": 80.0, "max": 89.99},
                    {"faixa": 2, "min": 90.0, "max": None},
                ]
            }
        }

    def test_usa_limites_do_mes(self):
        with patch.object(calculadora, "REGRAS", self.regras), \
             patch.object(calculadora, "METAS_MENSAIS", self.metas):
            res = calculadora.calcular("lider_frota", 500.0, {"nps": 92.0}, "2026-06")
        self.assertEqual(res["detalhes"]["nps"]["faixa"], 2)
        self.assertAlmostEqual(res["detalhes"]["nps"]["pct"], 0.08)

    def test_competencia_sem_meta_cadastrada_levanta_erro(self):
        with patch.object(calculadora, "REGRAS", self.regras), \
             patch.object(calculadora, "METAS_MENSAIS", self.metas):
            with self.assertRaises(KeyError):
                calculadora.calcular("lider_frota", 500.0, {"nps": 92.0}, "2026-07")


class TestDependenciaEntreIndicadores(unittest.TestCase):
    def setUp(self):
        self.regras = {
            "atendente": {
                "dma": _regra(
                    [{"faixa": 1, "min": 0.0, "max": None, "pct": 0.05}],
                    depende_indicador="faturamento", depende_valor_min=100.0,
                ),
                "faturamento": _regra([{"faixa": 1, "min": 0.0, "max": None, "pct": 0.02}]),
            }
        }

    def test_bloqueia_quando_dependencia_nao_atingida(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular(
                "atendente", 1000.0, {"dma": 45.0, "faturamento": 80.0}, "2026-06",
            )
        dma = res["detalhes"]["dma"]
        self.assertTrue(dma["bloqueado"])
        self.assertEqual(dma["pct"], 0.0)
        self.assertIn("faturamento >= 100.0", dma["motivo_bloqueio"])
        # o indicador do qual dma depende não é afetado pelo bloqueio
        self.assertFalse(res["detalhes"]["faturamento"]["bloqueado"])
        self.assertAlmostEqual(res["detalhes"]["faturamento"]["pct"], 0.02)

    def test_libera_quando_dependencia_atingida(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular(
                "atendente", 1000.0, {"dma": 45.0, "faturamento": 100.0}, "2026-06",
            )
        dma = res["detalhes"]["dma"]
        self.assertFalse(dma["bloqueado"])
        self.assertAlmostEqual(dma["pct"], 0.05)

    def test_rv_base_soma_todos_os_indicadores_nao_bloqueados(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular(
                "atendente", 1000.0, {"dma": 45.0, "faturamento": 100.0}, "2026-06",
            )
        # 1000*0.05 (dma) + 1000*0.02 (faturamento) = 70.0
        self.assertAlmostEqual(res["rv_base"], 70.0)


class TestRegraEspecificaPorLoja(unittest.TestCase):
    def setUp(self):
        self.regras = {
            "atendente": {
                "dma": {
                    None: {
                        "direcao": "maior", "chave_meta": None,
                        "depende_indicador": None, "depende_valor_min": None,
                        "faixas": [{"faixa": 1, "min": 0.0, "max": None, "pct": 0.03}],
                    },
                    "SAO10": {
                        "direcao": "maior", "chave_meta": None,
                        "depende_indicador": None, "depende_valor_min": None,
                        "faixas": [{"faixa": 1, "min": 0.0, "max": None, "pct": 0.09}],
                    },
                }
            }
        }

    def test_usa_regra_da_loja_quando_existe(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 50.0}, "2026-06", unidade="SAO10")
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.09)

    def test_cai_na_regra_padrao_para_loja_sem_regra_especifica(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 50.0}, "2026-06", unidade="REC01")
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.03)

    def test_cai_na_regra_padrao_quando_loja_nao_informada(self):
        with patch.object(calculadora, "REGRAS", self.regras):
            res = calculadora.calcular("atendente", 1000.0, {"dma": 50.0}, "2026-06")
        self.assertAlmostEqual(res["detalhes"]["dma"]["pct"], 0.03)


if __name__ == "__main__":
    unittest.main()
