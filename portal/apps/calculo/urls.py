from django.urls import path

from . import views

app_name = "calculo"

urlpatterns = [
    path("", views.executar, name="executar"),
    path("arquivos/", views.arquivos, name="arquivos"),
    path("resultado/<int:pk>/", views.resultado, name="resultado"),
    path("historico/", views.historico, name="historico"),
]
