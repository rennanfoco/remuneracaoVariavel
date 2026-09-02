"""
Cria o grupo "Gestão RV" (permissão de editar regras de negócio) se não
existir, e concede a ele as permissões de add/change/delete/view sobre os
models do app regras. Idempotente — pode ser rodado quantas vezes for
preciso (ex: depois de adicionar um novo model em regras).

Uso: python manage.py bootstrap_grupos
"""

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from apps.regras import models as regras_models


class Command(BaseCommand):
    help = "Cria/atualiza o grupo de permissão para edição de regras de negócio."

    def handle(self, *args, **options):
        grupo, criado = Group.objects.get_or_create(name=settings.GRUPO_GESTAO_RV)

        modelos = [
            regras_models.Grupo,
            regras_models.Cargo,
            regras_models.IndicadorRegra,
            regras_models.FaixaCalculo,
            regras_models.MetaMensal,
            regras_models.MetaFaturamentoRegional,
            regras_models.Loja,
            regras_models.ParametroTOTVS,
        ]

        permissoes = Permission.objects.filter(
            content_type__in=[ContentType.objects.get_for_model(m) for m in modelos],
        )
        grupo.permissions.set(permissoes)

        acao = "criado" if criado else "atualizado"
        self.stdout.write(self.style.SUCCESS(
            f"Grupo '{grupo.name}' {acao} com {permissoes.count()} permissões "
            f"sobre {len(modelos)} models de regras."
        ))
