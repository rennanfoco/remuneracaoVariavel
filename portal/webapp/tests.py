"""Testes da configuração (webapp/settings.py)."""

from django.test import SimpleTestCase

from webapp.settings import _resolver_debug


class TestResolverDebug(SimpleTestCase):
    def test_variavel_explicita_ligada_manda_em_qualquer_comando(self):
        self.assertTrue(_resolver_debug({"DJANGO_DEBUG": "1"}, ["gunicorn"]))

    def test_variavel_explicita_desligada_manda_ate_no_runserver(self):
        # permite testar localmente como se fosse produção
        self.assertFalse(_resolver_debug({"DJANGO_DEBUG": "0"}, ["manage.py", "runserver"]))

    def test_so_o_valor_1_liga(self):
        self.assertFalse(_resolver_debug({"DJANGO_DEBUG": "true"}, ["manage.py", "runserver"]))

    def test_sem_variavel_em_producao_fica_fechado(self):
        # gunicorn/WSGI (e qualquer comando que não seja de desenvolvimento): esquecer a variável não abre nada
        self.assertFalse(_resolver_debug({}, ["gunicorn", "webapp.wsgi"]))
        self.assertFalse(_resolver_debug({}, []))
        self.assertFalse(_resolver_debug({}, ["manage.py", "migrate"]))

    def test_sem_variavel_o_servidor_de_desenvolvimento_e_os_testes_ficam_abertos(self):
        self.assertTrue(_resolver_debug({}, ["manage.py", "runserver", "8000"]))
        self.assertTrue(_resolver_debug({}, ["manage.py", "test", "apps"]))
