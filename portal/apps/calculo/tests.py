"""
Testes de apps/calculo — formatação de célula usada na visualização web do relatório (views.py), o
status atual dos arquivos de uma competência, a validação no envio, a busca no TOTVS e a orquestração
do cálculo (services.py), e as abas Arquivos e Cálculo. O motor de cálculo nunca roda de verdade aqui
(subprocess mockado) — isso é responsabilidade dos testes de motor_calculo/.
"""

import datetime
import io
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from . import services
from .models import ArquivoCompetencia, ExecucaoCalculo
from .views import _fmt_moeda, _fmt_numero, _fmt_pct, _formatar_celula, _ler_relatorio


class TestFormatacao(TestCase):
    def test_fmt_moeda_no_padrao_brasileiro(self):
        self.assertEqual(_fmt_moeda(1234.5), "R$ 1.234,50")

    def test_fmt_moeda_valor_pequeno(self):
        self.assertEqual(_fmt_moeda(7), "R$ 7,00")

    def test_fmt_pct(self):
        self.assertEqual(_fmt_pct(103.456), "103,5%")

    def test_fmt_numero(self):
        self.assertEqual(_fmt_numero(1234.5), "1.234,5")

    def test_formatar_celula_moeda(self):
        self.assertEqual(_formatar_celula("Valor_Total_RV (R$)", 1500.0), {"texto": "R$ 1.500,00", "ord": 1500.0})

    def test_formatar_celula_elegivel(self):
        self.assertEqual(_formatar_celula("Elegível", True), {"texto": "Sim", "ord": 1})
        self.assertEqual(_formatar_celula("Elegível", False), {"texto": "Não", "ord": 0})

    def test_formatar_celula_nan_vira_travessao(self):
        import pandas as pd
        self.assertEqual(_formatar_celula("DMA", pd.NA), {"texto": "—", "ord": ""})


class TestExecutarCalculo(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("rh", password="senha123")

    def _nova_execucao(self):
        return ExecucaoCalculo.objects.create(competencia="2026-06", iniciado_por=self.usuario)

    @patch("apps.calculo.services.subprocess.run")
    def test_execucao_bem_sucedida_marca_concluido(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="processado com sucesso", stderr="",
        )
        execucao = self._nova_execucao()

        services.executar_calculo(execucao)

        execucao.refresh_from_db()
        self.assertEqual(execucao.status, "concluido")
        self.assertEqual(execucao.log, "processado com sucesso")
        self.assertIsNotNone(execucao.concluido_em)

    @patch("apps.calculo.services.subprocess.run")
    def test_processo_com_erro_marca_status_erro(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Falha ao ler colaboradores_rm.csv",
        )
        execucao = self._nova_execucao()

        services.executar_calculo(execucao)

        execucao.refresh_from_db()
        self.assertEqual(execucao.status, "erro")
        self.assertEqual(execucao.erro_mensagem, "Falha ao ler colaboradores_rm.csv")

    @patch("apps.calculo.services.subprocess.run")
    def test_timeout_marca_status_erro(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=services.TIMEOUT_SEGUNDOS)
        execucao = self._nova_execucao()

        services.executar_calculo(execucao)

        execucao.refresh_from_db()
        self.assertEqual(execucao.status, "erro")
        self.assertIn("tempo limite", execucao.erro_mensagem)

    @patch("apps.calculo.services.subprocess.run")
    def test_erro_do_motor_na_saida_normal_aparece_como_mensagem(self, mock_run):
        stdout = (
            "Carregando arquivos de entrada...\nCalculando RV...\n"
            "[ERRO] Meta 'nps_outros' nao encontrada para competencia '2026-09'.\n  Adicione o bloco em Metas_Mensais."
        )
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")
        execucao = self._nova_execucao()

        services.executar_calculo(execucao)

        execucao.refresh_from_db()
        self.assertEqual(execucao.status, "erro")
        self.assertEqual(
            execucao.erro_mensagem,
            "Meta 'nps_outros' nao encontrada para competencia '2026-09'.\n  Adicione o bloco em Metas_Mensais.",
        )

    @patch("apps.calculo.services.subprocess.run")
    def test_erro_sem_stderr_usa_mensagem_padrao(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        execucao = self._nova_execucao()

        services.executar_calculo(execucao)

        execucao.refresh_from_db()
        self.assertEqual(execucao.status, "erro")
        self.assertTrue(execucao.erro_mensagem)  # mensagem padrão, não vazia


class _ComArquivos(TestCase):
    """Base: usuário, MEDIA_ROOT temporário e um atalho para criar arquivos de uma competência."""

    def setUp(self):
        self.usuario = User.objects.create_user("rh", password="senha123")
        media = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media.name))

    def arquivo(self, competencia, tipo, nome=None, origem="upload", conteudo=b"x"):
        nome = nome or f"{tipo}.csv"
        return ArquivoCompetencia.objects.create(
            competencia=competencia, tipo=tipo, arquivo=SimpleUploadedFile(nome, conteudo), nome_original=nome,
            origem=origem, enviado_por=self.usuario,
        )

    def tudo_menos_colaboradores(self, competencia):
        for tipo in ("coral", "nps", "preventiva", "bate_patio", "meta_faturamento", "mapeamento"):
            self.arquivo(competencia, tipo)

    def motor_ok(self):
        return patch("apps.calculo.services.subprocess.run", return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr="",
        ))


class TestNomeCanonico(TestCase):
    def test_coral_vai_como_dma_pro_rata(self):
        self.assertEqual(services.nome_canonico("coral", "dma-pro-rata-Setembro-2026.csv"), "dma-pro-rata.csv")

    def test_metas_em_xlsx_vao_como_base_metas(self):
        self.assertEqual(services.nome_canonico("meta_faturamento", "Base metas Setembro (1).xlsx"), "Base metas.xlsx")

    def test_metas_em_csv_do_formato_antigo_continuam_como_importacao_planilha(self):
        self.assertEqual(
            services.nome_canonico("meta_faturamento", "Importação Planilha 05.2026.csv"), "Importação Planilha.csv",
        )

    def test_colaboradores(self):
        self.assertEqual(services.nome_canonico("colaboradores", "qualquer.csv"), "colaboradores_rm.csv")


class TestSituacaoDaCompetencia(_ComArquivos):
    def _item(self, situacao, tipo):
        return next(i for i in situacao.itens if i.tipo == tipo)

    def test_competencia_vazia_nao_pode_calcular_e_nonrev_e_opcional(self):
        s = services.situacao_da_competencia("2026-09")
        self.assertFalse(s.pode_calcular)
        self.assertEqual(len(s.pendencias), 7)  # os 7 obrigatórios; NONREV não conta
        self.assertTrue(self._item(s, "nonrev").ok)

    def test_tudo_menos_colaboradores_bloqueia_com_mensagem_da_competencia(self):
        self.tudo_menos_colaboradores("2026-09")
        s = services.situacao_da_competencia("2026-09")
        self.assertFalse(s.pode_calcular)
        self.assertEqual(len(s.pendencias), 1)
        self.assertIn("base de colaboradores da competência 2026-09", s.pendencias[0])

    def test_buscar_no_totvs_resolve_a_pendencia_de_colaboradores(self):
        self.tudo_menos_colaboradores("2026-09")
        s = services.situacao_da_competencia("2026-09", buscar_totvs=True)
        self.assertTrue(s.pode_calcular)
        self.assertTrue(self._item(s, "colaboradores").buscar_agora)

    def test_base_de_colaboradores_de_outra_competencia_nao_vale(self):
        self.tudo_menos_colaboradores("2026-09")
        self.arquivo("2026-08", "colaboradores")
        self.assertFalse(services.situacao_da_competencia("2026-09").pode_calcular)

    def test_base_de_colaboradores_da_competencia_libera_sem_buscar(self):
        self.tudo_menos_colaboradores("2026-09")
        self.arquivo("2026-09", "colaboradores")
        self.assertTrue(services.situacao_da_competencia("2026-09").pode_calcular)

    def test_vale_a_base_de_colaboradores_mais_recente_seja_import_ou_totvs(self):
        self.arquivo("2026-09", "colaboradores", "antigo.csv", origem="upload")
        recente_totvs = self.arquivo("2026-09", "colaboradores", "totvs.csv", origem="totvs")
        self.assertEqual(self._item(services.situacao_da_competencia("2026-09"), "colaboradores").arquivo, recente_totvs)

        recente_upload = self.arquivo("2026-09", "colaboradores", "novo.csv", origem="upload")
        self.assertEqual(self._item(services.situacao_da_competencia("2026-09"), "colaboradores").arquivo, recente_upload)

    def test_lista_de_logins_e_herdada_da_competencia_anterior_mais_recente(self):
        self.arquivo("2026-07", "mapeamento", "jul.xlsx")
        agosto = self.arquivo("2026-08", "mapeamento", "ago.xlsx")
        item = self._item(services.situacao_da_competencia("2026-09"), "mapeamento")
        self.assertTrue(item.herdado)
        self.assertEqual(item.arquivo, agosto)
        self.assertTrue(item.ok)

    def test_lista_de_logins_da_propria_competencia_nao_e_herdada(self):
        self.arquivo("2026-08", "mapeamento")
        setembro = self.arquivo("2026-09", "mapeamento")
        item = self._item(services.situacao_da_competencia("2026-09"), "mapeamento")
        self.assertFalse(item.herdado)
        self.assertEqual(item.arquivo, setembro)

    def test_lista_de_logins_de_competencia_futura_nao_vale(self):
        self.arquivo("2026-10", "mapeamento")
        self.assertFalse(self._item(services.situacao_da_competencia("2026-09"), "mapeamento").ok)

    def test_outros_arquivos_nunca_sao_herdados(self):
        self.arquivo("2026-08", "coral")
        self.assertFalse(self._item(services.situacao_da_competencia("2026-09"), "coral").ok)

    def test_competencia_padrao_e_a_mais_recente_com_arquivos(self):
        self.arquivo("2026-07", "coral")
        self.arquivo("2026-09", "coral")
        self.assertEqual(services.competencia_padrao(), "2026-09")

    def test_competencia_padrao_sem_arquivos_e_o_mes_anterior(self):
        with patch("apps.calculo.services.timezone.localdate", return_value=datetime.date(2026, 1, 15)):
            self.assertEqual(services.competencia_padrao(), "2025-12")


class TestValidarArquivo(_ComArquivos):
    def _upload(self):
        return SimpleUploadedFile("dma-pro-rata.csv", b"LOGIN,LOJA\n")

    def _resposta(self, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    @patch("apps.calculo.services._rodar_script")
    def test_devolve_o_json_do_validador(self, rodar):
        esperado = {"ok": True, "erros": [], "avisos": ["a"], "resumo": "2 logins"}
        rodar.return_value = self._resposta(stdout=json.dumps(esperado))
        self.assertEqual(services.validar_arquivo("coral", self._upload(), "2026-09"), esperado)
        args = rodar.call_args.args
        self.assertEqual(args[0], "validar_arquivo.py")
        self.assertIn("--competencia", args[1])

    @patch("apps.calculo.services._rodar_script")
    def test_falha_do_processo_vira_erro(self, rodar):
        rodar.return_value = self._resposta(returncode=1, stderr="Traceback...\nValueError: quebrou")
        r = services.validar_arquivo("coral", self._upload(), "2026-09")
        self.assertFalse(r["ok"])
        self.assertIn("quebrou", r["erros"][0])

    @patch("apps.calculo.services._rodar_script")
    def test_resposta_que_nao_e_json_vira_erro(self, rodar):
        rodar.return_value = self._resposta(stdout="lixo")
        self.assertFalse(services.validar_arquivo("coral", self._upload(), "2026-09")["ok"])

    @patch("apps.calculo.services._rodar_script")
    def test_timeout_vira_erro(self, rodar):
        rodar.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=1)
        r = services.validar_arquivo("coral", self._upload(), "2026-09")
        self.assertFalse(r["ok"])
        self.assertIn("demorou", r["erros"][0])


class TestBuscarColaboradoresTotvs(_ComArquivos):
    CSV = (
        "matricula;nome;cargo;unidade;regional;salario_base;dias_trabalhados\n"
        "00123;Ana;ATENDENTE I;SAO10;SUDESTE;1800.0;30\n"
    )

    def _motor_que_grava(self, competencia_esperada="2026-09"):
        def rodar(script, args, referencias, timeout):
            self.assertEqual(script, "exportar_colaboradores.py")
            self.assertEqual(args[args.index("--competencia") + 1], competencia_esperada)
            Path(args[args.index("--saida") + 1]).write_bytes(self.CSV.encode("utf-8"))
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="1 colaboradores gravados em x.csv", stderr="")
        return rodar

    def test_guarda_a_base_como_colaboradores_da_competencia(self):
        with patch("apps.calculo.services._rodar_script", side_effect=self._motor_que_grava()):
            arquivo = services.buscar_colaboradores_totvs("2026-09", self.usuario)
        self.assertEqual((arquivo.competencia, arquivo.tipo, arquivo.origem), ("2026-09", "colaboradores", "totvs"))
        self.assertEqual(arquivo.resumo, "1 colaboradores")
        self.assertEqual(arquivo.arquivo.read().decode("utf-8"), self.CSV)
        self.assertEqual(arquivo.enviado_por, self.usuario)

    def test_erro_do_totvs_vira_erro_totvs_sem_gravar_nada(self):
        resposta = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="[ERRO] 401 Client Error: Unauthorized")
        with patch("apps.calculo.services._rodar_script", return_value=resposta):
            with self.assertRaises(services.ErroTotvs) as ctx:
                services.buscar_colaboradores_totvs("2026-09", self.usuario)
        self.assertIn("401 Client Error: Unauthorized", str(ctx.exception))
        self.assertEqual(ArquivoCompetencia.objects.count(), 0)

    def test_timeout_vira_erro_totvs(self):
        with patch("apps.calculo.services._rodar_script", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=1)):
            with self.assertRaises(services.ErroTotvs):
                services.buscar_colaboradores_totvs("2026-09", self.usuario)


class TestIniciarCalculo(_ComArquivos):
    def test_sem_colaboradores_da_competencia_e_sem_buscar_bloqueia_e_nao_cria_execucao(self):
        self.tudo_menos_colaboradores("2026-09")
        with self.assertRaises(services.CalculoBloqueado) as ctx:
            services.iniciar_calculo("2026-09", self.usuario, buscar_totvs=False)
        self.assertIn("colaboradores", ctx.exception.pendencias[0])
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)

    def test_falta_de_outro_arquivo_bloqueia_mesmo_buscando_no_totvs_e_nem_chega_a_buscar(self):
        self.arquivo("2026-09", "coral")
        with patch("apps.calculo.services.buscar_colaboradores_totvs") as buscar:
            with self.assertRaises(services.CalculoBloqueado):
                services.iniciar_calculo("2026-09", self.usuario, buscar_totvs=True)
        buscar.assert_not_called()
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)

    def test_calcula_com_a_base_guardada_sem_buscar_no_totvs(self):
        self.tudo_menos_colaboradores("2026-09")
        base = self.arquivo("2026-09", "colaboradores")
        with self.motor_ok(), patch("apps.calculo.services.buscar_colaboradores_totvs") as buscar:
            execucao = services.iniciar_calculo("2026-09", self.usuario)
        buscar.assert_not_called()
        self.assertEqual(execucao.status, "concluido")
        self.assertFalse(execucao.usar_api_totvs)
        self.assertIn(base, execucao.arquivos_usados.all())
        self.assertEqual(execucao.arquivos_usados.count(), 7)

    def test_buscando_no_totvs_a_execucao_usa_a_base_recem_buscada(self):
        self.tudo_menos_colaboradores("2026-09")
        antiga = self.arquivo("2026-09", "colaboradores", "antiga.csv")

        def buscar(competencia, usuario):
            return self.arquivo(competencia, "colaboradores", "colaboradores_totvs_2026-09.csv", origem="totvs")

        with self.motor_ok(), patch("apps.calculo.services.buscar_colaboradores_totvs", side_effect=buscar):
            execucao = services.iniciar_calculo("2026-09", self.usuario, buscar_totvs=True)
        usada = execucao.arquivos_usados.get(tipo="colaboradores")
        self.assertEqual(usada.origem, "totvs")
        self.assertNotEqual(usada, antiga)
        self.assertTrue(execucao.usar_api_totvs)

    def test_totvs_fora_do_ar_nao_cria_execucao(self):
        self.tudo_menos_colaboradores("2026-09")
        with patch("apps.calculo.services.buscar_colaboradores_totvs", side_effect=services.ErroTotvs("fora do ar")):
            with self.assertRaises(services.ErroTotvs):
                services.iniciar_calculo("2026-09", self.usuario, buscar_totvs=True)
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)

    def test_lista_de_logins_herdada_entra_nos_arquivos_usados(self):
        self.tudo_menos_colaboradores("2026-09")
        ArquivoCompetencia.objects.filter(competencia="2026-09", tipo="mapeamento").delete()
        anterior = self.arquivo("2026-08", "mapeamento", "logins.xlsx")
        self.arquivo("2026-09", "colaboradores")
        with self.motor_ok():
            execucao = services.iniciar_calculo("2026-09", self.usuario)
        self.assertIn(anterior, execucao.arquivos_usados.all())

    def test_substituir_um_arquivo_depois_nao_muda_o_que_a_execucao_usou(self):
        self.tudo_menos_colaboradores("2026-09")
        self.arquivo("2026-09", "colaboradores")
        with self.motor_ok():
            execucao = services.iniciar_calculo("2026-09", self.usuario)
        usado = execucao.arquivos_usados.get(tipo="coral")
        self.arquivo("2026-09", "coral", "coral_novo.csv")
        self.assertEqual(execucao.arquivos_usados.get(tipo="coral"), usado)


class TestArquivosCopiadosParaOMotor(_ComArquivos):
    """O portal copia cada arquivo usado para uma pasta temporária com o nome que o motor espera."""

    def _pasta_de_entrada(self, arquivos):
        execucao = ExecucaoCalculo.objects.create(competencia="2026-09", iniciado_por=self.usuario)
        execucao.arquivos_usados.set(arquivos)
        vistos = {}

        def motor_falso(comando, **kwargs):
            pasta = Path(comando[comando.index("--input") + 1])
            vistos["arquivos"] = sorted(p.name for p in pasta.iterdir())
            self.assertNotIn("--api", comando)
            return subprocess.CompletedProcess(args=comando, returncode=0, stdout="", stderr="")

        with patch("apps.calculo.services.subprocess.run", side_effect=motor_falso):
            services.executar_calculo(execucao)
        return vistos["arquivos"]

    def test_nomes_canonicos_na_pasta_de_entrada(self):
        arquivos = [
            self.arquivo("2026-09", "coral", "dma-pro-rata-Setembro-2026.csv"),
            self.arquivo("2026-09", "meta_faturamento", "Base metas Setembro (1).xlsx"),
            self.arquivo("2026-09", "colaboradores", "colaboradores_totvs_2026-09.csv", origem="totvs"),
        ]
        self.assertEqual(
            self._pasta_de_entrada(arquivos), ["Base metas.xlsx", "colaboradores_rm.csv", "dma-pro-rata.csv"],
        )

    def test_metas_em_csv_do_formato_antigo(self):
        self.assertEqual(
            self._pasta_de_entrada([self.arquivo("2026-09", "meta_faturamento", "Importação Planilha 05.2026.csv")]),
            ["Importação Planilha.csv"],
        )


class TestAbaArquivos(_ComArquivos):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("calculo:arquivos")).status_code, 302)

    def test_mostra_o_status_da_competencia_escolhida(self):
        self.arquivo("2026-09", "coral", "dma-pro-rata-Setembro-2026.csv")
        resposta = self.client.get(reverse("calculo:arquivos"), {"competencia": "2026-09"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "dma-pro-rata-Setembro-2026.csv")
        self.assertEqual(resposta.context["competencia"], "2026-09")

    def test_competencia_invalida_cai_na_padrao(self):
        self.arquivo("2026-07", "coral")
        resposta = self.client.get(reverse("calculo:arquivos"), {"competencia": "lixo"})
        self.assertEqual(resposta.context["competencia"], "2026-07")

    def test_lista_as_versoes_anteriores(self):
        self.arquivo("2026-09", "coral", "v1.csv")
        self.arquivo("2026-09", "coral", "v2.csv")
        resposta = self.client.get(reverse("calculo:arquivos"), {"competencia": "2026-09"})
        linha = next(l for l in resposta.context["linhas"] if l["item"].tipo == "coral")
        self.assertEqual(linha["item"].arquivo.nome_original, "v2.csv")
        self.assertEqual([a.nome_original for a in linha["anteriores"]], ["v1.csv"])

    @patch("apps.calculo.services.validar_arquivo")
    def test_envio_valido_guarda_o_arquivo_na_competencia(self, validar):
        validar.return_value = {"ok": True, "erros": [], "avisos": ["parece de outro mês"], "resumo": "2 logins"}
        resposta = self.client.post(reverse("calculo:arquivos"), {
            "competencia": "2026-09", "tipo": "coral", "arquivo": SimpleUploadedFile("dma-pro-rata.csv", b"x"),
        }, follow=True)
        guardado = ArquivoCompetencia.objects.get()
        self.assertEqual((guardado.competencia, guardado.tipo, guardado.enviado_por), ("2026-09", "coral", self.usuario))
        self.assertEqual(guardado.resumo, "2 logins")
        self.assertEqual(guardado.lista_de_avisos, ["parece de outro mês"])
        textos = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(any("arquivo recebido" in t for t in textos))
        self.assertTrue(any("parece de outro mês" in t for t in textos))
        self.assertEqual(resposta.redirect_chain[-1][0], reverse("calculo:arquivos") + "?competencia=2026-09")

    @patch("apps.calculo.services.validar_arquivo")
    def test_envio_recusado_pela_validacao_nao_guarda_nada(self, validar):
        validar.return_value = {"ok": False, "erros": ["Coluna esperada não encontrada: 'LOGIN'."], "avisos": [], "resumo": ""}
        resposta = self.client.post(reverse("calculo:arquivos"), {
            "competencia": "2026-09", "tipo": "coral", "arquivo": SimpleUploadedFile("errado.csv", b"x"),
        }, follow=True)
        self.assertEqual(ArquivoCompetencia.objects.count(), 0)
        self.assertTrue(any("não aceito" in str(m) for m in resposta.context["messages"]))

    def test_envio_sem_arquivo_avisa(self):
        resposta = self.client.post(reverse("calculo:arquivos"), {"competencia": "2026-09", "tipo": "coral"}, follow=True)
        self.assertEqual(ArquivoCompetencia.objects.count(), 0)
        self.assertTrue(any("Escolha o arquivo" in str(m) for m in resposta.context["messages"]))


class TestAbaCalculo(_ComArquivos):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("calculo:executar")).status_code, 302)

    def test_mostra_o_checklist_da_competencia(self):
        self.tudo_menos_colaboradores("2026-09")
        resposta = self.client.get(reverse("calculo:executar"), {"competencia": "2026-09"})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.context["situacao"].pode_calcular)
        self.assertIsNone(resposta.context["colaboradores"].arquivo)
        self.assertEqual(resposta.context["outras_pendencias"], [])
        self.assertContains(resposta, "Ainda não há base de colaboradores de 2026-09")

    def test_post_sem_colaboradores_da_competencia_e_sem_buscar_e_bloqueado(self):
        self.tudo_menos_colaboradores("2026-09")
        resposta = self.client.post(reverse("calculo:executar"), {"competencia": "2026-09"}, follow=True)
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)
        self.assertTrue(any("base de colaboradores da competência 2026-09" in str(m) for m in resposta.context["messages"]))

    def test_post_com_base_guardada_calcula_e_vai_para_o_resultado(self):
        self.tudo_menos_colaboradores("2026-09")
        self.arquivo("2026-09", "colaboradores")
        with self.motor_ok():
            resposta = self.client.post(reverse("calculo:executar"), {"competencia": "2026-09"})
        execucao = ExecucaoCalculo.objects.get()
        self.assertRedirects(resposta, reverse("calculo:resultado", args=[execucao.pk]), fetch_redirect_response=False)

    def test_post_buscando_no_totvs_chama_a_busca(self):
        self.tudo_menos_colaboradores("2026-09")
        with self.motor_ok(), patch(
            "apps.calculo.services.buscar_colaboradores_totvs",
            side_effect=lambda c, u: self.arquivo(c, "colaboradores", origem="totvs"),
        ) as buscar:
            self.client.post(reverse("calculo:executar"), {"competencia": "2026-09", "buscar_totvs": "on"})
        buscar.assert_called_once()
        self.assertTrue(ExecucaoCalculo.objects.get().usar_api_totvs)

    def test_totvs_fora_do_ar_mostra_o_erro_e_nao_calcula(self):
        self.tudo_menos_colaboradores("2026-09")
        with patch("apps.calculo.services.buscar_colaboradores_totvs", side_effect=services.ErroTotvs("TOTVS fora do ar")):
            resposta = self.client.post(
                reverse("calculo:executar"), {"competencia": "2026-09", "buscar_totvs": "on"}, follow=True,
            )
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)
        self.assertTrue(any("TOTVS fora do ar" in str(m) for m in resposta.context["messages"]))

    def test_competencia_invalida_no_post(self):
        resposta = self.client.post(reverse("calculo:executar"), {"competencia": "2026-13"}, follow=True)
        self.assertEqual(ExecucaoCalculo.objects.count(), 0)
        self.assertTrue(any("Competência inválida" in str(m) for m in resposta.context["messages"]))

    def test_resultado_lista_os_arquivos_usados(self):
        self.tudo_menos_colaboradores("2026-09")
        self.arquivo("2026-09", "colaboradores", "colab.csv")
        with self.motor_ok():
            execucao = services.iniciar_calculo("2026-09", self.usuario)
        resposta = self.client.get(reverse("calculo:resultado", args=[execucao.pk]))
        self.assertContains(resposta, "Arquivos usados neste cálculo")
        self.assertContains(resposta, "colab.csv")


class TestRelatorioComNaoCalculados(_ComArquivos):
    """Quem ficou de fora por cargo sem grupo aparece na tela de resultado (aba "Não calculados" do relatório)."""

    def _execucao_com_relatorio(self, nao_calculados=None):
        resumo = pd.DataFrame([{
            "Grupo RV": "atendente", "Total": 2, "Elegíveis": 2, "Com_Prêmio": 1,
            "Valor_Total_RV": 150.0, "Prêmio_Médio": 75.0, "Salário_Total_Folha": 3800.0,
        }])
        detalhado = pd.DataFrame([{"Matrícula": "1", "Nome": "Ana", "Elegível": True}, {"Matrícula": "2", "Nome": "Bia", "Elegível": True}])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as w:
            detalhado.to_excel(w, sheet_name="Detalhado", index=False)
            resumo.to_excel(w, sheet_name="Resumo por Grupo", index=False)
            if nao_calculados is not None:
                nao_calculados.to_excel(w, sheet_name="Não calculados", index=False)
        execucao = ExecucaoCalculo.objects.create(competencia="2026-09", iniciado_por=self.usuario, status="concluido")
        execucao.arquivo_relatorio.save("rv_2026-09_relatorio.xlsx", ContentFile(buffer.getvalue()))
        return execucao

    def _nao_calculados(self):
        return pd.DataFrame([
            {"Matrícula": "10", "Nome": "Caio", "Cargo": "ATENDENTE II", "Unidade": "SAO10", "Regional": "SUDESTE",
             "Salário Base (R$)": 2000.0, "Dias Trabalhados": 30, "Motivo": "Cargo sem grupo de cálculo"},
            {"Matrícula": "11", "Nome": "Dani", "Cargo": "ATENDENTE II", "Unidade": "REC20", "Regional": "NORDESTE",
             "Salário Base (R$)": 2100.0, "Dias Trabalhados": 15, "Motivo": "Cargo sem grupo de cálculo"},
            {"Matrícula": "12", "Nome": "Edu", "Cargo": "MOTORISTA I", "Unidade": "SAO10", "Regional": "SUDESTE",
             "Salário Base (R$)": 1900.0, "Dias Trabalhados": 30, "Motivo": "Cargo sem grupo de cálculo"},
        ])

    def test_le_a_aba_e_resume_por_cargo(self):
        relatorio = _ler_relatorio(self._execucao_com_relatorio(self._nao_calculados()))
        self.assertEqual(relatorio["resumo_geral"]["nao_calculados"], 3)
        sem_calculo = relatorio["sem_calculo"]
        self.assertEqual(sem_calculo["total"], 3)
        self.assertEqual(
            sem_calculo["por_cargo"],
            [{"cargo": "ATENDENTE II", "quantidade": 2}, {"cargo": "MOTORISTA I", "quantidade": 1}],
        )
        self.assertEqual(len(sem_calculo["linhas"]), 3)
        self.assertIn("Motivo", sem_calculo["colunas"])

    def test_sem_a_aba_nao_ha_aviso(self):
        relatorio = _ler_relatorio(self._execucao_com_relatorio())
        self.assertEqual(relatorio["resumo_geral"]["nao_calculados"], 0)
        self.assertIsNone(relatorio["sem_calculo"])

    def test_pagina_de_resultado_mostra_o_aviso_e_os_cargos(self):
        self.client.force_login(self.usuario)
        execucao = self._execucao_com_relatorio(self._nao_calculados())
        pagina = self.client.get(reverse("calculo:resultado", args=[execucao.pk]))
        self.assertContains(pagina, "3 colaboradores não foram calculados")
        self.assertContains(pagina, "ATENDENTE II")
        self.assertContains(pagina, "MOTORISTA I")

    def test_pagina_de_resultado_sem_nao_calculados_nao_tem_o_aviso(self):
        self.client.force_login(self.usuario)
        execucao = self._execucao_com_relatorio()
        pagina = self.client.get(reverse("calculo:resultado", args=[execucao.pk]))
        self.assertNotContains(pagina, "não foram calculados")
