from django.urls import path

from . import views

app_name = "calculo"

urlpatterns = [
    path("", views.executar, name="executar"),
    path("resultado/<int:pk>/", views.resultado, name="resultado"),
    path("historico/", views.historico, name="historico"),
]
