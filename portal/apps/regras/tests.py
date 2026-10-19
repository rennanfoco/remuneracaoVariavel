"""
Testes de apps/regras — validação de regra duplicada (loja específica x
padrão), permissões das telas (usuário comum x Gestão RV) e o mecanismo de
desfazer/refazer uma importação inteira (services.reverter_importacao /
reaplicar_importacao), que é o ponto mais novo e mais arriscado do app.
"""

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from simple_history.utils import update_change_reason

from . import services
from .models import Grupo, ImportacaoReferencias, IndicadorRegra, Loja


class TestValidacaoIndicadorRegra(TestCase):
    def setUp(self):
        self.grupo = Grupo.objects.create(nome="atendente", modelo="percentual")
        self.loja = Loja.objects.create(unidade="SAO10", regional="SUDESTE")

    def test_duas_regras_padrao_para_o_mesmo_indicador_e_bloqueado(self):
        IndicadorRegra.objects.create(grupo=self.grupo, indicador="dma")
        duplicata = IndicadorRegra(grupo=self.grupo, indicador="dma")
        with self.assertRaises(ValidationError):
            duplicata.clean()

    def test_duas_regras_para_a_mesma_loja_e_bloqueado(self):
        IndicadorRegra.objects.create(grupo=self.grupo, indicador="dma", loja=self.loja)
        duplicata = IndicadorRegra(grupo=self.grupo, indicador="dma", loja=self.loja)
        with self.assertRaises(ValidationError):
            duplicata.clean()

    def test_regra_padrao_e_regra_da_loja_podem_coexistir(self):
        IndicadorRegra.objects.create(grupo=self.grupo, indicador="dma")
        especifica = IndicadorRegra(grupo=self.grupo, indicador="dma", loja=self.loja)
        especifica.clean()  # não deve levantar
        especifica.save()
        self.assertEqual(IndicadorRegra.objects.filter(grupo=self.grupo, indicador="dma").count(), 2)

    def test_editar_a_propria_regra_nao_conflita_consigo_mesma(self):
        regra = IndicadorRegra.objects.create(grupo=self.grupo, indicador="dma")
        regra.direcao = "menor"
        regra.clean()  # não deve levantar por "conflitar" com ela mesma


class TestPermissoesDasTelas(TestCase):
    def setUp(self):
        self.grupo_gestao_rv, _ = Group.objects.get_or_create(name=settings.GRUPO_GESTAO_RV)
        self.usuario_comum = User.objects.create_user("comum", password="senha123")
        self.usuario_admin = User.objects.create_user("admin_rv", password="senha123")
        self.usuario_admin.groups.add(self.grupo_gestao_rv)

    def test_visualizar_acessivel_a_qualquer_usuario_logado(self):
        self.client.force_login(self.usuario_comum)
        resposta = self.client.get(reverse("regras:visualizar"))
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.context["e_admin"])

    def test_visualizar_marca_e_admin_para_gestao_rv(self):
        self.client.force_login(self.usuario_admin)
        resposta = self.client.get(reverse("regras:visualizar"))
        self.assertTrue(resposta.context["e_admin"])

    def test_visualizar_exige_login(self):
        resposta = self.client.get(reverse("regras:visualizar"))
        self.assertEqual(resposta.status_code, 302)

    def test_exportar_acessivel_a_qualquer_usuario_logado(self):
        self.client.force_login(self.usuario_comum)
        resposta = self.client.get(reverse("regras:exportar"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_importar_bloqueado_para_usuario_comum(self):
        self.client.force_login(self.usuario_comum)
        resposta = self.client.get(reverse("regras:importar"))
        self.assertEqual(resposta.status_code, 403)

    def test_importar_permitido_para_gestao_rv(self):
        self.client.force_login(self.usuario_admin)
        resposta = self.client.get(reverse("regras:importar"))
        self.assertEqual(resposta.status_code, 200)

    def test_historico_importacoes_bloqueado_para_usuario_comum(self):
        self.client.force_login(self.usuario_comum)
        resposta = self.client.get(reverse("regras:historico_importacoes"))
        self.assertEqual(resposta.status_code, 403)

    def test_reverter_bloqueado_para_usuario_comum(self):
        importacao = ImportacaoReferencias.objects.create(
            arquivo_nome="ref.xlsx", importado_por=self.usuario_admin,
            identificador_lote="lote-x", resumo="",
        )
        self.client.force_login(self.usuario_comum)
        resposta = self.client.post(reverse("regras:reverter", args=[importacao.pk]))
        self.assertEqual(resposta.status_code, 403)


class TestReverterEReaplicarImportacao(TestCase):
    """
    Cobre o mecanismo de desfazer/refazer uma importação inteira de uma vez
    (ver services._restaurar_lote): tanto o caso de um registro ALTERADO por
    ela (volta pro valor anterior / volta pro valor novo) quanto o caso de um
    registro CRIADO por ela (reverter apaga, reaplicar recria).
    """

    def setUp(self):
        self.usuario = User.objects.create_user("rh", password="senha123")

    def test_reverter_restaura_valor_anterior_e_reaplicar_restaura_o_novo(self):
        grupo = Grupo.objects.create(nome="mecanico", modelo="teto_fixo")
        update_change_reason(grupo, "lote-criacao")  # fora do lote sob teste

        grupo.modelo = "percentual"
        grupo.save()
        update_change_reason(grupo, "lote-2")

        importacao = ImportacaoReferencias.objects.create(
            arquivo_nome="ref.xlsx", importado_por=self.usuario,
            identificador_lote="lote-2", resumo="1 grupo",
        )

        avisos = services.reverter_importacao(importacao, self.usuario)
        self.assertEqual(avisos, [])
        grupo.refresh_from_db()
        self.assertEqual(grupo.modelo, "teto_fixo")
        importacao.refresh_from_db()
        self.assertEqual(importacao.status, "revertida")
        self.assertEqual(importacao.alterado_por, self.usuario)

        avisos = services.reaplicar_importacao(importacao, self.usuario)
        self.assertEqual(avisos, [])
        grupo.refresh_from_db()
        self.assertEqual(grupo.modelo, "percentual")
        importacao.refresh_from_db()
        self.assertEqual(importacao.status, "aplicada")

    def test_reverter_um_registro_criado_pela_importacao_apaga_o_registro(self):
        grupo = Grupo.objects.create(nome="novo_grupo", modelo="percentual")
        update_change_reason(grupo, "lote-criou")
        pk_criado = grupo.pk

        importacao = ImportacaoReferencias.objects.create(
            arquivo_nome="ref.xlsx", importado_por=self.usuario,
            identificador_lote="lote-criou", resumo="1 grupo novo",
        )

        avisos = services.reverter_importacao(importacao, self.usuario)
        self.assertEqual(avisos, [])
        self.assertFalse(Grupo.objects.filter(pk=pk_criado).exists())

        avisos = services.reaplicar_importacao(importacao, self.usuario)
        self.assertEqual(avisos, [])
        self.assertTrue(Grupo.objects.filter(pk=pk_criado, nome="novo_grupo").exists())

    def test_reverter_duas_vezes_e_idempotente_e_avisa(self):
        grupo = Grupo.objects.create(nome="idempotente", modelo="percentual")
        update_change_reason(grupo, "lote-3")
        importacao = ImportacaoReferencias.objects.create(
            arquivo_nome="ref.xlsx", importado_por=self.usuario,
            identificador_lote="lote-3", resumo="",
        )

        services.reverter_importacao(importacao, self.usuario)
        importacao.refresh_from_db()
        avisos = services.reverter_importacao(importacao, self.usuario)
        self.assertEqual(avisos, ["Esta importação já está revertida."])
        self.assertEqual(importacao.status, "revertida")
