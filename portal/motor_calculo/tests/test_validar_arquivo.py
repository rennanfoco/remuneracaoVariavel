"""
Testes de validar_arquivo.py (validação no envio, aba Arquivos do portal) e do CSV de colaboradores
gerado a partir da API do TOTVS (rv.totvs_client.salvar_colaboradores_csv).
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

import validar_arquivo
from rv import loader
from rv.totvs_client import COLUNAS_CSV, salvar_colaboradores_csv

CORAL_PRO_RATA = (
    "CONTRATOS,RETIRADA,DEVOLUCAO,LOGIN,LOJA,OPCIONAL,PREMIAVEL,DIAS_NO_PERIODO,VALOR_VENDIDO_PRO_RATA\n"
    "SAO000001-26,2026-08-20,2026-09-10,ana,SAO10,LDW,yes,10,400.00\n"
    "SAO000002-26,2026-09-05,2026-10-02,bia,REC20,LDW,yes,20,300.50\n"
)


class _ComArquivosTemporarios(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)

    def _escrever(self, nome: str, conteudo: str) -> str:
        caminho = self.pasta / nome
        caminho.write_text(conteudo, encoding="utf-8")
        return str(caminho)


class TestValidarCoral(_ComArquivosTemporarios):
    def test_arquivo_pro_rata_do_mes_certo_e_aceito_com_resumo(self):
        r = validar_arquivo.validar("coral", self._escrever("c.csv", CORAL_PRO_RATA), "2026-09")
        self.assertTrue(r["ok"])
        self.assertEqual(r["erros"], [])
        self.assertEqual(r["avisos"], [])
        self.assertEqual(r["resumo"], "2 logins, R$ 700,50 faturados")

    def test_arquivo_de_outro_mes_e_aceito_mas_avisa(self):
        r = validar_arquivo.validar("coral", self._escrever("c.csv", CORAL_PRO_RATA), "2026-08")
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["avisos"]), 1)
        self.assertIn("retirada em 05/09/2026", r["avisos"][0])

    def test_coluna_ausente_e_erro_com_dica_das_colunas_esperadas(self):
        sem_valor = CORAL_PRO_RATA.replace("VALOR_VENDIDO_PRO_RATA", "OUTRA_COISA")
        r = validar_arquivo.validar("coral", self._escrever("c.csv", sem_valor), "2026-09")
        self.assertFalse(r["ok"])
        self.assertIn("VALOR_VENDIDO_PRO_RATA", r["erros"][0])

    def test_arquivo_so_com_cabecalho_e_erro(self):
        cabecalho = CORAL_PRO_RATA.splitlines()[0] + "\n"
        r = validar_arquivo.validar("coral", self._escrever("c.csv", cabecalho), "2026-09")
        self.assertFalse(r["ok"])


class TestValidarMetas(_ComArquivosTemporarios):
    def test_base_metas_xlsx(self):
        caminho = self.pasta / "Base metas.xlsx"
        with pd.ExcelWriter(caminho) as w:
            pd.DataFrame([
                ["Login", "Nome", "Centro de Custo", "DMA", "Valor"],
                ["rgan", "A", "CWB10", 45.45, 1000.0],
                ["drs", "B", "FLN10", 45.45, 2500.5],
            ]).to_excel(w, sheet_name="Planilha1", header=False, index=False)
        r = validar_arquivo.validar("meta_faturamento", str(caminho), "2026-09")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["resumo"], "2 metas em 2 lojas, total R$ 3.500,50")

    def test_planilha_sem_coluna_de_loja_e_erro(self):
        r = validar_arquivo.validar(
            "meta_faturamento", self._escrever("m.csv", "Nome;Usuário;Meta de Faturamento\nA;rgan;100\n"), "2026-09",
        )
        self.assertFalse(r["ok"])
        self.assertIn("coluna da loja", r["erros"][0])


class TestValidarOutros(_ComArquivosTemporarios):
    def test_tipo_desconhecido(self):
        r = validar_arquivo.validar("xyz", self._escrever("x.csv", "a"), "2026-09")
        self.assertFalse(r["ok"])
        self.assertIn("desconhecido", r["erros"][0])

    def test_avisos_do_loader_sao_repassados(self):
        # cargo que não está na aba Cargos: o loader avisa por print, o validador devolve como aviso
        colab = pd.DataFrame([{
            "matricula": "00123", "nome": "A", "cargo": "CARGO QUE NAO EXISTE XYZ", "unidade": "SAO10",
            "regional": "SUDESTE", "salario_base": 1800.0, "dias_trabalhados": 30,
        }])
        caminho = self.pasta / "colab.csv"
        salvar_colaboradores_csv(colab, caminho)
        r = validar_arquivo.validar("colaboradores", str(caminho))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["resumo"], "1 colaboradores")
        self.assertEqual(len(r["avisos"]), 1)
        self.assertIn("CARGO QUE NAO EXISTE XYZ", r["avisos"][0])


class TestCsvDeColaboradoresDoTotvs(_ComArquivosTemporarios):
    def test_ida_e_volta_preserva_matricula_com_zeros_e_dias_trabalhados(self):
        df = pd.DataFrame([{
            "matricula": "00123", "nome": "Ana Souza", "cargo": "ATENDENTE I", "unidade": "SAO10",
            "regional": "SUDESTE", "salario_base": 1800.5, "dias_trabalhados": 15,
            "grupo_calculo": "atendente",  # extra: não vai para o CSV
        }])
        caminho = self.pasta / "colaboradores_rm.csv"
        salvar_colaboradores_csv(df, caminho)

        lido = pd.read_csv(caminho, sep=";", dtype=str, encoding="utf-8-sig")
        self.assertEqual(list(lido.columns), COLUNAS_CSV)

        processado = loader._proc_colaboradores(loader._ler_csv(caminho))
        self.assertEqual(processado["matricula"].iloc[0], "00123")
        self.assertEqual(processado["dias_trabalhados"].iloc[0], 15)
        self.assertAlmostEqual(processado["salario_base"].iloc[0], 1800.5)
        self.assertEqual(processado["cargo"].iloc[0], "ATENDENTE I")


if __name__ == "__main__":
    unittest.main()
