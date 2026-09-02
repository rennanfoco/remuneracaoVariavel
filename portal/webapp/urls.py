"""
URLs — Portal de Remuneração Variável.

/                  redireciona para o cálculo
/calculo/          rodar cálculo, histórico, download de resultados
/regras/           ver regras atuais + exportar planilha (todo mundo);
                    importar planilha + reverter/reaplicar (só Gestão RV)
/admin/            edição registro-a-registro (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais)
/contas/           login/logout (login normal do Django em dev local)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="calculo:executar", permanent=False)),
    path("admin/", admin.site.urls),
    path("calculo/", include("apps.calculo.urls")),
    path("regras/", include("apps.regras.urls")),
    path(
        "contas/login/",
        auth_views.LoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("contas/logout/", auth_views.LogoutView.as_view(), name="logout"),
]

if settings.DEBUG:
    # Em produção (Azure App Service), mídia deve ser servida por um storage
    # externo (ex: Azure Blob) — servir do filesystem local só em dev.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
