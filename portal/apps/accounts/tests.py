"""
Testes de apps/accounts — checagem de papel (e_admin_rv/query_admin_rv) e
sincronização automática de is_staff com o grupo Gestão RV (signals.py).
"""

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import TestCase

from .utils import e_admin_rv, query_admin_rv


class TestEAdminRv(TestCase):
    def setUp(self):
        self.grupo_gestao_rv, _ = Group.objects.get_or_create(name=settings.GRUPO_GESTAO_RV)

    def test_superusuario_e_admin_mesmo_sem_grupo(self):
        superuser = User.objects.create_superuser("chefe", "chefe@foco.com", "senha123")
        self.assertTrue(e_admin_rv(superuser))

    def test_membro_do_grupo_gestao_rv_e_admin(self):
        usuario = User.objects.create_user("rh", password="senha123")
        usuario.groups.add(self.grupo_gestao_rv)
        self.assertTrue(e_admin_rv(usuario))

    def test_usuario_comum_nao_e_admin(self):
        usuario = User.objects.create_user("comum", password="senha123")
        self.assertFalse(e_admin_rv(usuario))

    def test_usuario_anonimo_nao_e_admin(self):
        self.assertFalse(e_admin_rv(AnonymousUser()))

    def test_query_admin_rv_filtra_os_mesmos_usuarios_que_e_admin_rv(self):
        superuser = User.objects.create_superuser("chefe2", "chefe2@foco.com", "senha123")
        membro = User.objects.create_user("rh2", password="senha123")
        membro.groups.add(self.grupo_gestao_rv)
        comum = User.objects.create_user("comum2", password="senha123")

        admins = set(User.objects.filter(query_admin_rv()).values_list("username", flat=True))
        self.assertIn(superuser.username, admins)
        self.assertIn(membro.username, admins)
        self.assertNotIn(comum.username, admins)


class TestSincronizacaoStaffComGestaoRv(TestCase):
    def setUp(self):
        self.grupo_gestao_rv, _ = Group.objects.get_or_create(name=settings.GRUPO_GESTAO_RV)

    def test_entrar_no_grupo_concede_is_staff(self):
        usuario = User.objects.create_user("novo", password="senha123")
        self.assertFalse(usuario.is_staff)

        usuario.groups.add(self.grupo_gestao_rv)

        usuario.refresh_from_db()
        self.assertTrue(usuario.is_staff)

    def test_sair_do_grupo_revoga_is_staff(self):
        usuario = User.objects.create_user("saindo", password="senha123")
        usuario.groups.add(self.grupo_gestao_rv)
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_staff)

        usuario.groups.remove(self.grupo_gestao_rv)

        usuario.refresh_from_db()
        self.assertFalse(usuario.is_staff)

    def test_limpar_todos_os_grupos_tambem_revoga(self):
        usuario = User.objects.create_user("limpando", password="senha123")
        usuario.groups.add(self.grupo_gestao_rv)
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_staff)

        usuario.groups.clear()

        usuario.refresh_from_db()
        self.assertFalse(usuario.is_staff)

    def test_superusuario_mantem_staff_mesmo_saindo_do_grupo(self):
        superuser = User.objects.create_superuser("chefe3", "chefe3@foco.com", "senha123")
        superuser.groups.add(self.grupo_gestao_rv)
        superuser.groups.remove(self.grupo_gestao_rv)

        superuser.refresh_from_db()
        self.assertTrue(superuser.is_staff)

    def test_adicionar_a_outro_grupo_nao_mexe_em_is_staff(self):
        outro_grupo = Group.objects.create(name="Outro Grupo Qualquer")
        usuario = User.objects.create_user("neutro", password="senha123")

        usuario.groups.add(outro_grupo)

        usuario.refresh_from_db()
        self.assertFalse(usuario.is_staff)
