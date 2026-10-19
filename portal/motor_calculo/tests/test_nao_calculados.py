"""
Testes do tratamento de colaboradores cujo cargo não tem grupo de cálculo (aba Cargos do
referencias.xlsx): eles NÃO são calculados — não há parâmetros definidos para eles, e o motor não
assume nenhum (antes caíam num grupo "outros" genérico) — e aparecem num aviso e na aba "Não
calculados" do relatório.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from rv import engine, loader, output


def _colaboradores_brutos():
    return pd.DataFrame([
        {"matricula": "1", "nome": "Ana", "cargo": "atendente i", "unidade": "sao10", "regional": "sudeste",
         "salario_base": "1800,50", "dias_trabalhados": "30"},
        {"matricula": "2", "nome": "Bia", "cargo": "Atendente II", "unidade": "SAO10", "regional": "SUDESTE",
         "salario_base": "2000", "dias_trabalhados": "30"},
        {"matricula": "3", "nome": "Caio", "cargo": "ATENDENTE II", "unidade": "REC20", "regional": "NORDESTE",
         "salario_base": "2000", "dias_trabalhados": "15"},
    ])


class TestAtribuirGrupoCalculo(unittest.TestCase):
    def _processar(self):
        saida = io.StringIO()
        with patch.object(loader, "CARGOS_GRUPO", {"ATENDENTE I": "atendente"}), contextlib.redirect_stdout(saida):
            df = loader._proc_colaboradores(_colaboradores_brutos())
        return df, saida.getvalue()

    def test_cargo_mapeado_recebe_o_grupo(self):
        df, _ = self._processar()
        self.assertEqual(df.loc[df["matricula"] == "1", "grupo_calculo"].iloc[0], "atendente")

    def test_cargo_sem_mapeamento_fica_sem_grupo_e_nao_cai_em_outros(self):
        df, _ = self._processar()
        sem_mapeamento = df[df["matricula"].isin(["2", "3"])]
        self.assertTrue(sem_mapeamento["grupo_calculo"].isna().all())
        self.assertNotIn("outros", set(df["grupo_calculo"].dropna()))

    def test_avisa_quantos_nao_serao_calculados_e_de_quais_cargos(self):
        _, saida = self._processar()
        self.assertIn("2 colaborador(es)", saida)
        self.assertIn("NÃO serão calculados", saida)
        self.assertIn("ATENDENTE II (2)", saida)

    def test_sem_cargo_fora_do_mapa_nao_avisa(self):
        saida = io.StringIO()
        mapa = {"ATENDENTE I": "atendente", "ATENDENTE II": "atendente"}
        with patch.object(loader, "CARGOS_GRUPO", mapa), contextlib.redirect_stdout(saida):
            loader._proc_colaboradores(_colaboradores_brutos())
        self.assertEqual(saida.getvalue(), "")


class TestSepararNaoCalculados(unittest.TestCase):
    def _colab(self, grupos):
        return pd.DataFrame([
            {"matricula": str(i), "nome": f"P{i}", "cargo": "C", "unidade": "SAO10", "regional": "SUDESTE",
             "salario_base": 1800.0, "dias_trabalhados": 30, "grupo": g}
            for i, g in enumerate(grupos, start=1)
        ])

    def test_separa_quem_tem_grupo_de_quem_nao_tem(self):
        calculaveis, nao_calculados = engine._separar_nao_calculados(self._colab(["atendente", None, ""]))
        self.assertEqual(list(calculaveis["matricula"]), ["1"])
        self.assertEqual(list(nao_calculados["matricula"]), ["2", "3"])

    def test_tabela_de_nao_calculados_traz_o_motivo(self):
        _, nao_calculados = engine._separar_nao_calculados(self._colab(["atendente", None]))
        self.assertEqual(
            list(nao_calculados.columns),
            ["matricula", "nome", "cargo", "unidade", "regional", "salario_base", "dias_trabalhados", "motivo"],
        )
        self.assertIn("sem grupo de cálculo", nao_calculados["motivo"].iloc[0])

    def test_todos_com_grupo_nao_devolve_ninguem(self):
        calculaveis, nao_calculados = engine._separar_nao_calculados(self._colab(["atendente", "gestor"]))
        self.assertEqual(len(calculaveis), 2)
        self.assertTrue(nao_calculados.empty)


class TestRelatorioComNaoCalculados(unittest.TestCase):
    def _resultados(self):
        return pd.DataFrame([{
            "matricula": "1", "nome": "Ana", "cargo": "ATENDENTE I", "grupo": "atendente", "unidade": "SAO10",
            "regional": "SUDESTE", "salario_base": 1800.0, "dias_trabalhados": 30, "elegivel": True,
            "rv_base": 100.0, "rv_final": 100.0,
        }])

    def _nao_calculados(self):
        return pd.DataFrame([{
            "matricula": "2", "nome": "Bia", "cargo": "ATENDENTE II", "unidade": "SAO10", "regional": "SUDESTE",
            "salario_base": 2000.0, "dias_trabalhados": 30,
            "motivo": "Cargo sem grupo de cálculo (aba Cargos do referencias.xlsx)",
        }])

    def _abas(self, nao_calculados):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            caminho = output.gerar_relatorio(self._resultados(), "2026-09", Path(tmp), nao_calculados)
            with pd.ExcelFile(caminho) as xls:
                abas = xls.sheet_names
                nao = xls.parse("Não calculados") if "Não calculados" in abas else None
        return abas, nao

    def test_aba_nao_calculados_lista_quem_ficou_de_fora(self):
        abas, nao = self._abas(self._nao_calculados())
        self.assertEqual(abas, ["Detalhado", "Resumo por Grupo", "Não calculados"])
        self.assertEqual(nao["Matrícula"].astype(str).tolist(), ["2"])
        self.assertEqual(nao["Cargo"].tolist(), ["ATENDENTE II"])
        self.assertIn("Motivo", nao.columns)

    def test_sem_nao_calculados_a_aba_nao_existe(self):
        self.assertEqual(self._abas(None)[0], ["Detalhado", "Resumo por Grupo"])
        self.assertEqual(self._abas(self._nao_calculados().iloc[0:0])[0], ["Detalhado", "Resumo por Grupo"])

    def test_quem_nao_foi_calculado_nao_entra_no_detalhado(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            caminho = output.gerar_relatorio(self._resultados(), "2026-09", Path(tmp), self._nao_calculados())
            with pd.ExcelFile(caminho) as xls:
                detalhado = xls.parse("Detalhado")
        self.assertEqual(detalhado["Matrícula"].astype(str).tolist(), ["1"])


if __name__ == "__main__":
    unittest.main()
