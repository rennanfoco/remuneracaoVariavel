"""Testes de rv/eligibility.py — elegibilidade e proporcionalidade da RV."""

import unittest

from rv.eligibility import aplicar_proporcionalidade, is_elegivel


class TestIsElegivel(unittest.TestCase):
    def test_zero_dias_trabalhados_e_inelegivel(self):
        elegivel, motivo = is_elegivel({"dias_trabalhados": 0})
        self.assertFalse(elegivel)
        self.assertEqual(motivo, "Zero dias trabalhados")

    def test_dias_trabalhados_parcial_e_elegivel(self):
        elegivel, motivo = is_elegivel({"dias_trabalhados": 15})
        self.assertTrue(elegivel)
        self.assertEqual(motivo, "")

    def test_mes_completo_e_elegivel(self):
        elegivel, _ = is_elegivel({"dias_trabalhados": 30})
        self.assertTrue(elegivel)

    def test_campo_ausente_assume_mes_completo(self):
        elegivel, _ = is_elegivel({})
        self.assertTrue(elegivel)


class TestAplicarProporcionalidade(unittest.TestCase):
    def test_mes_completo_nao_altera_valor(self):
        self.assertAlmostEqual(aplicar_proporcionalidade(100.0, 30), 100.0)

    def test_mais_de_30_dias_tambem_nao_altera(self):
        # não deveria acontecer na prática, mas a função não deve reduzir.
        self.assertAlmostEqual(aplicar_proporcionalidade(100.0, 31), 100.0)

    def test_proporcional_por_dias_trabalhados(self):
        # 15 de 30 dias = metade.
        self.assertAlmostEqual(aplicar_proporcionalidade(100.0, 15), 50.0)

    def test_zero_dias_trabalhados_zera_o_valor(self):
        self.assertAlmostEqual(aplicar_proporcionalidade(100.0, 0), 0.0)

    def test_resultado_e_arredondado_a_duas_casas(self):
        # 100 / 30 * 10 = 33.333... -> 33.33
        self.assertAlmostEqual(aplicar_proporcionalidade(100.0, 10), 33.33)


if __name__ == "__main__":
    unittest.main()
