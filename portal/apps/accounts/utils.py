"""
Checagem de papel do usuário — única fonte de verdade pra "isso é admin RV
ou não", usada em apps/accounts/admin.py, apps/regras/views.py e onde mais
precisar. Antes essa mesma regra (superusuário OU membro do grupo Gestão RV)
estava duplicada em três lugares — cada um podia divergir silenciosamente
se um dia alguém mudasse um sem lembrar do outro.
"""

from django.conf import settings
from django.db.models import Q


def e_admin_rv(user) -> bool:
    """Superusuário ou membro do grupo Gestão RV — a definição de "admin" deste projeto."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=settings.GRUPO_GESTAO_RV).exists()


def query_admin_rv() -> Q:
    """Mesma checagem acima, como Q — pra filtrar QuerySets de User (ex: list_filter do admin)."""
    return Q(is_superuser=True) | Q(groups__name=settings.GRUPO_GESTAO_RV)
