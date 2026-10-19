"""
Testes de rv/loader.py — leitura do arquivo do Coral no formato pro rata (e no antigo, por
fechamento), da planilha de metas nova (Base metas, xlsx) e da antiga (Importação Planilha, csv),
e a conferência do período do arquivo contra a competência.
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from rv import loader


def _coral_pro_rata():
    # Um contrato por linha-base: DIAS_NO_PERIODO só vem na linha do item base, como no arquivo real.
    return pd.DataFrame([
        {"LOGIN": "ana", "LOJA": "sao10", "PREMIAVEL": "yes", "DIAS_NO_PERIODO": "10", "VALOR_VENDIDO_PRO_RATA": "400.00"},
        {"LOGIN": "ana", "LOJA": "sao10", "PREMIAVEL": "no",  "DIAS_NO_PERIODO": "5",  "VALOR_VENDIDO_PRO_RATA": "100.00"},
        {"LOGIN": "ana", "LOJA": "rec20", "PREMIAVEL": "voucher-required", "DIAS_NO_PERIODO": "10", "VALOR_VENDIDO_PRO_RATA": "300.00"},
        {"LOGIN": "bia", "LOJA": "rec20", "PREMIAVEL": "yes", "DIAS_NO_PERIODO": "0",  "VALOR_VENDIDO_PRO_RATA": "50.00"},
    ])


class TestCoralProRata(unittest.TestCase):
    def test_faturamento_soma_todas_as_linhas_e_dma_so_as_premiaveis(self):
        r = loader._proc_coral(_coral_pro_rata()).set_index("login_coral")
        # ana: 400 + 100 + 300 = 800 vendido; premiável (<> no): 400 + 300 = 700 em 20 dias
        self.assertAlmostEqual(r.loc["ana", "faturamento_realizado"], 800.0)
        self.assertAlmostEqual(r.loc["ana", "dma_valor"], 700.0)
        self.assertAlmostEqual(r.loc["ana", "dma_dias"], 20.0)
        self.assertAlmostEqual(r.loc["ana", "dma"], 35.0)

    def test_login_sem_dias_premiaveis_tem_dma_zero(self):
        r = loader._proc_coral(_coral_pro_rata()).set_index("login_coral")
        self.assertAlmostEqual(r.loc["bia", "dma"], 0.0)

    def test_loja_do_login_e_a_mais_frequente(self):
        r = loader._proc_coral(_coral_pro_rata()).set_index("login_coral")
        self.assertEqual(r.loc["ana", "unidade"], "SAO10")

    def test_faturamento_por_loja_do_contrato(self):
        r = loader._proc_coral_por_loja(_coral_pro_rata()).set_index("unidade")
        self.assertAlmostEqual(r.loc["SAO10", "fat_realizado_loja"], 500.0)
        self.assertAlmostEqual(r.loc["REC20", "fat_realizado_loja"], 350.0)

    def test_formato_antigo_por_fechamento_continua_aceito(self):
        antigo = _coral_pro_rata().rename(columns={
            "VALOR_VENDIDO_PRO_RATA": "VALOR VENDIDO", "DIAS_NO_PERIODO": "DIAS",
        })
        r = loader._proc_coral(antigo).set_index("login_coral")
        self.assertAlmostEqual(r.loc["ana", "faturamento_realizado"], 800.0)
        self.assertAlmostEqual(r.loc["ana", "dma"], 35.0)

    def test_valor_com_virgula_decimal_continua_funcionando(self):
        df = _coral_pro_rata()
        df["VALOR_VENDIDO_PRO_RATA"] = df["VALOR_VENDIDO_PRO_RATA"].str.replace(".", ",")
        r = loader._proc_coral(df).set_index("login_coral")
        self.assertAlmostEqual(r.loc["ana", "faturamento_realizado"], 800.0)


class TestVerificarPeriodoCoral(unittest.TestCase):
    def _df(self, retirada, devolucao):
        return pd.DataFrame({"RETIRADA": retirada, "DEVOLUCAO": devolucao})

    def test_arquivo_do_mes_certo_nao_avisa(self):
        # contrato que cruza o mês: retirou em junho, devolve em outubro — está dentro dos limites
        df = self._df(["2026-06-09", "2026-09-16"], ["2026-10-08", "2026-09-27"])
        self.assertEqual(loader.verificar_periodo_coral(df, "2026-09"), [])

    def test_retirada_depois_do_fim_do_mes_avisa(self):
        df = self._df(["2026-09-16", "2026-10-02"], ["2026-10-10", "2026-10-12"])
        avisos = loader.verificar_periodo_coral(df, "2026-09")
        self.assertEqual(len(avisos), 1)
        self.assertIn("retirada em 02/10/2026", avisos[0])

    def test_devolucao_antes_do_inicio_do_mes_avisa(self):
        df = self._df(["2026-07-01"], ["2026-08-31"])
        avisos = loader.verificar_periodo_coral(df, "2026-09")
        self.assertEqual(len(avisos), 1)
        self.assertIn("devolução em 31/08/2026", avisos[0])

    def test_datas_no_formato_brasileiro_do_arquivo_antigo(self):
        df = self._df(["01/04/2026", "31/05/2026"], ["01/05/2026", "31/05/2026"])
        self.assertEqual(loader.verificar_periodo_coral(df, "2026-05"), [])
        self.assertEqual(len(loader.verificar_periodo_coral(df, "2026-06")), 1)  # devolução em maio, antes de junho

    def test_arquivo_sem_colunas_de_data_avisa_que_nao_conseguiu_conferir(self):
        avisos = loader.verificar_periodo_coral(_coral_pro_rata(), "2026-09")
        self.assertEqual(len(avisos), 1)
        self.assertIn("RETIRADA e DEVOLUCAO", avisos[0])


class TestMetaFaturamento(unittest.TestCase):
    def test_formato_novo_base_metas(self):
        df = pd.DataFrame({
            "Login": ["rgan", "DRS"], "Nome": ["A", "B"], "Centro de Custo": ["cwb10", "CWB10"],
            "DMA": ["45.45", "45.45"], "Valor": ["42643.0906", "43612.25175"],
        })
        r = loader._proc_meta_faturamento(df)
        self.assertEqual(list(r.columns), ["login_coral", "unidade", "meta_faturamento"])
        self.assertEqual(list(r["login_coral"]), ["rgan", "drs"])
        self.assertEqual(list(r["unidade"]), ["CWB10", "CWB10"])
        self.assertAlmostEqual(r["meta_faturamento"].iloc[0], 42643.0906)  # valor exato, sem arredondar

    def test_formato_antigo_importacao_planilha_pula_linha_de_nomes_em_ingles(self):
        df = pd.DataFrame({
            "Usuário": ["user_login", "rgan"],
            "Meta de Faturamento": ["billing_goal", "36527"],
            "Loja": ["store_id", "CWB10"],
        })
        r = loader._proc_meta_faturamento(df)
        self.assertEqual(len(r), 1)
        self.assertEqual(r["login_coral"].iloc[0], "rgan")
        self.assertEqual(r["unidade"].iloc[0], "CWB10")
        self.assertAlmostEqual(r["meta_faturamento"].iloc[0], 36527.0)

    def test_sem_coluna_de_loja_e_erro_claro(self):
        df = pd.DataFrame({"Login": ["rgan"], "Valor": ["100"]})
        with self.assertRaises(ValueError) as ctx:
            loader._proc_meta_faturamento(df)
        self.assertIn("coluna da loja", str(ctx.exception))

    def test_meta_vazia_vira_zero(self):
        df = pd.DataFrame({"Login": ["rgan"], "Centro de Custo": ["CWB10"], "Valor": [None]})
        self.assertAlmostEqual(loader._proc_meta_faturamento(df)["meta_faturamento"].iloc[0], 0.0)


class TestLerMeta(unittest.TestCase):
    def test_xlsx_com_varias_abas_usa_a_que_tem_login_centro_de_custo_e_valor(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            caminho = Path(tmp) / "Base metas.xlsx"
            with pd.ExcelWriter(caminho) as w:
                pd.DataFrame([["Loja", "Agregado"], ["FLN10", 100]]).to_excel(w, sheet_name="Lojas", header=False, index=False)
                pd.DataFrame([
                    ["Login", "Nome", "Centro de Custo", "DMA", "Valor"],
                    ["rgan", "A", "CWB10", 45.45, 42643.09],
                ]).to_excel(w, sheet_name="Planilha1", header=False, index=False)
            df = loader._ler_meta(caminho)
        self.assertEqual(list(df.columns)[:5], ["Login", "Nome", "Centro de Custo", "DMA", "Valor"])
        self.assertEqual(df["Login"].iloc[0], "rgan")

    def test_xlsx_sem_aba_de_metas_e_erro_claro(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            caminho = Path(tmp) / "Base metas.xlsx"
            with pd.ExcelWriter(caminho) as w:
                pd.DataFrame([["Loja", "Agregado"], ["FLN10", 100]]).to_excel(w, sheet_name="Lojas", header=False, index=False)
            with self.assertRaises(ValueError) as ctx:
                loader._ler_meta(caminho)
        self.assertIn("Login, Centro de Custo e Valor", str(ctx.exception))

    def test_csv_do_formato_antigo_e_lido_direto(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            caminho = Path(tmp) / "Importação Planilha 05.2026.csv"
            caminho.write_text("Nome;Usuário;Meta de Faturamento;Loja\nA;rgan;36527;CWB10\n", encoding="utf-8")
            df = loader._ler_meta(caminho)
        self.assertEqual(df["Usuário"].iloc[0], "rgan")


class TestEncontrarArquivo(unittest.TestCase):
    def test_coral_aceita_pro_rata_e_o_formato_antigo(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pasta = Path(tmp)
            (pasta / "dma-accumulated-maio.csv").write_text("x")
            self.assertEqual(loader._encontrar(pasta, loader.PADROES["coral"]).name, "dma-accumulated-maio.csv")

    def test_pro_rata_tem_preferencia_quando_os_dois_existem(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pasta = Path(tmp)
            (pasta / "dma-accumulated-maio.csv").write_text("x")
            (pasta / "dma-pro-rata-Setembro-2026.csv").write_text("x")
            self.assertEqual(loader._encontrar(pasta, loader.PADROES["coral"]).name, "dma-pro-rata-Setembro-2026.csv")

    def test_metas_aceitam_base_metas_xlsx_e_importacao_planilha_csv(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pasta = Path(tmp)
            (pasta / "Importação Planilha 05.2026.csv").write_text("x", encoding="utf-8")
            self.assertEqual(loader._encontrar(pasta, loader.PADROES["meta_faturamento"]).suffix, ".csv")
            (pasta / "Base metas Setembro (1).xlsx").write_text("x")
            self.assertEqual(loader._encontrar(pasta, loader.PADROES["meta_faturamento"]).suffix, ".xlsx")

    def test_arquivo_ausente_devolve_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self.assertIsNone(loader._encontrar(Path(tmp), loader.PADROES["coral"]))


if __name__ == "__main__":
    unittest.main()
