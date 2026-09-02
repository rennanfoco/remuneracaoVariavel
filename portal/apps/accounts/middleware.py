"""
Integração com a autenticação do Azure App Service ("Easy Auth" / App Service
Authentication).

Quando o app roda atrás do App Service com Easy Auth habilitado (produção),
o Azure AD autentica a requisição ANTES dela chegar no Django e injeta a
identidade do usuário via headers HTTP (X-MS-CLIENT-PRINCIPAL-NAME contém o
e-mail/UPN). Este middleware lê esse header e resolve/cria o User Django
correspondente, deixando `request.user` já autenticado — sem senha, sem
formulário de login.

Em desenvolvimento local (ou qualquer ambiente sem Easy Auth na frente) o
header simplesmente não existe, e o middleware não faz nada — o fluxo normal
de login do Django (django.contrib.auth) continua funcionando.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group

EASY_AUTH_HEADER = "HTTP_X_MS_CLIENT_PRINCIPAL_NAME"


class EasyAuthMiddleware:
    """
    Se o header do Easy Auth estiver presente e o usuário ainda não estiver
    autenticado na sessão, autentica automaticamente com base no e-mail
    injetado pelo Azure AD. Não substitui nem interfere no login normal do
    Django quando o header não existe.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        principal_name = request.META.get(EASY_AUTH_HEADER)

        if principal_name and (not request.user or not request.user.is_authenticated):
            user = _resolver_usuario(principal_name)
            if user is not None:
                # backend explícito pois o AuthenticationMiddleware já roda
                # antes deste e o usuário não passou por authenticate().
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        return self.get_response(request)


def _resolver_usuario(email: str):
    """Busca ou cria o usuário Django correspondente ao e-mail do Azure AD."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return None

    User = get_user_model()
    username = email.split("@")[0]

    user, criado = User.objects.get_or_create(
        email=email,
        defaults={"username": username, "is_active": True},
    )
    if criado:
        # Novo usuário chegando via SSO corporativo: acesso básico (rodar
        # cálculo). Acesso a edição de regras é concedido manualmente
        # adicionando ao grupo GRUPO_GESTAO_RV pelo admin — não é automático.
        Group.objects.get_or_create(name=settings.GRUPO_GESTAO_RV)
    return user
