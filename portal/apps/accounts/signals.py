"""
Ser adicionado ao grupo "Gestão RV" já dá acesso ao /admin/ sozinho
(is_staff=True) — sem precisar marcar "membro da equipe" à parte. Tirar do
grupo revoga esse acesso, exceto para superusuários (que sempre têm acesso
total, independente de grupo).
"""

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db.models.signals import m2m_changed
from django.dispatch import receiver


def _grupo_gestao_rv_id():
    try:
        return Group.objects.get(name=settings.GRUPO_GESTAO_RV).pk
    except Group.DoesNotExist:
        return None


@receiver(m2m_changed, sender=User.groups.through)
def sincronizar_staff_com_gestao_rv(sender, instance, action, reverse, pk_set, **kwargs):
    if reverse or action not in ("post_add", "post_remove", "post_clear"):
        return

    gestao_rv_id = _grupo_gestao_rv_id()
    if gestao_rv_id is None:
        return
    if action != "post_clear" and (not pk_set or gestao_rv_id not in pk_set):
        return  # mudança não envolveu o grupo Gestao RV — nada a sincronizar

    usuario = instance
    if usuario.is_superuser:
        return  # superusuário sempre tem acesso, independente de grupo

    deveria_ser_staff = usuario.groups.filter(pk=gestao_rv_id).exists()
    if usuario.is_staff != deveria_ser_staff:
        usuario.is_staff = deveria_ser_staff
        usuario.save(update_fields=["is_staff"])
