from django.urls import path

from . import views

app_name = "regras"

urlpatterns = [
    path("", views.visualizar, name="visualizar"),
    path("exportar/", views.exportar, name="exportar"),
    path("importar/", views.importar, name="importar"),
    path("importacoes/", views.historico_importacoes, name="historico_importacoes"),
    path("importacoes/<int:pk>/reverter/", views.reverter, name="reverter"),
    path("importacoes/<int:pk>/reaplicar/", views.reaplicar, name="reaplicar"),
]
