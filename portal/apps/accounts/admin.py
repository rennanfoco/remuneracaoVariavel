"""
Customiza a tela padrão de Users do Django admin — dois ajustes:

1. Coluna/filtro "Papel": deixa visível quem é "Admin RV" (superusuário ou
   membro do grupo Gestao RV) e quem é usuário comum (só usa /calculo/, sem
   acesso a editar regras) — sem inventar um grupo vazio só pra isso.
2. Esconde o campo "Permissões de usuário" (a lista granular de ~32
   permissões individuais) do formulário — a intenção é que só o grupo
   importe; permissão avulsa por pessoa não é um caso de uso daqui.
   "Membro da equipe" (is_staff) continua visível, mas já é sincronizado
   automaticamente com o grupo Gestao RV — ver signals.py.
3. Tira "Grupos" da barra lateral (Autenticação e Autorização) — a tela de
   criar/editar grupo do Django é literalmente um seletor de permissão por
   permissão, o oposto do que este projeto quer (só dois papéis fixos,
   nenhum dos dois editável pela tela). O grupo "Gestao RV" continua
   existindo (criado por `python manage.py bootstrap_grupos`) e continua
   aparecendo normalmente no campo "Grupos" de cada usuário — só não dá
   mais pra criar grupo novo nem reconfigurar as permissões dele pela UI.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User

from .utils import e_admin_rv, query_admin_rv

# Título da aba do navegador / cabeçalho da página inicial do admin — o
# logo e a cor já vêm de templates/admin/base_site.html e static/css/admin-foco.css.
admin.site.site_title = "Portal RV"
admin.site.site_header = "Portal RV — Foco"
admin.site.index_title = "Editar regras e usuários"

admin.site.unregister(Group)


class PapelListFilter(admin.SimpleListFilter):
    title = "papel"
    parameter_name = "papel"

    def lookups(self, request, model_admin):
        return [
            ("admin", "Admin RV"),
            ("usuario", "Usuário (sem acesso a regras)"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "admin":
            return queryset.filter(query_admin_rv()).distinct()
        if self.value() == "usuario":
            return queryset.exclude(query_admin_rv()).distinct()
        return queryset


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = DjangoUserAdmin.list_display + ("papel",)
    list_filter = DjangoUserAdmin.list_filter + (PapelListFilter,)

    # Mesmo fieldsets padrão do Django, só sem "user_permissions" — o
    # controle de acesso daqui é só por grupo (ver docstring do módulo).
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email")}),
        (
            "Permissões",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups")},
        ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )

    @admin.display(description="Papel")
    def papel(self, obj):
        return "Admin RV" if e_admin_rv(obj) else "Usuário"
