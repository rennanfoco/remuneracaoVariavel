"""
Django settings — Portal de Remuneração Variável (V2).

Local (dev): usa SQLite e login normal do Django (não há Easy Auth fora do
Azure App Service). Produção: usa Postgres via DATABASE_URL e autenticação
via Azure AD (Easy Auth), ver apps/accounts/middleware.py.
"""

import os
import sys
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
# portal/ é autocontido: motor_calculo/ (config.py, main.py, rv/) mora DENTRO
# dele — uma cópia própria, não uma referência à pasta motor_calculo/ da raiz
# do repositório (essa é a versão standalone da CLI, usada fora do portal).
# Se um bug de cálculo for corrigido em um lado, replique no outro.
MOTOR_CALCULO_DIR = BASE_DIR / "motor_calculo"

# Permite `import config` / `import rv` de dentro do processo Django (usado
# por apps/regras/management/commands/importar_referencias.py) sem precisar
# alterar nada em motor_calculo/ — o motor continua um pacote independente,
# só ganha um sys.path a mais.
sys.path.insert(0, str(MOTOR_CALCULO_DIR))

# ---------------------------------------------------------------------------
# Segurança — controlados por variável de ambiente; nunca hardcode em prod.
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-somente-para-desenvolvimento-local-nao-usar-em-producao",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "apps.regras",
    "apps.calculo",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Lê o header do Azure App Service Easy Auth quando presente (produção);
    # sem efeito em desenvolvimento local (cai no login normal do Django).
    "apps.accounts.middleware.EasyAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "webapp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "webapp.wsgi.application"

# ---------------------------------------------------------------------------
# Banco de dados
# Local: SQLite (nenhuma configuração necessária).
# Produção: definir DATABASE_URL (ex: postgres://user:pass@host:5432/dbname).
# ---------------------------------------------------------------------------
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# Só valida senha do login local (dev/fallback) — em produção, com Easy
# Auth/Azure AD, ninguém digita senha aqui. CommonPasswordValidator
# desativado por pedido explícito (rejeitava senhas razoáveis demais no
# dia a dia local); tamanho mínimo reduzido de 8 para 6.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    # {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internacionalização
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Arquivos estáticos e de mídia (uploads mensais, TXT/relatório gerados)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "calculo:executar"
LOGOUT_REDIRECT_URL = "login"

# Nome do grupo Django com permissão de editar as regras de negócio
# (ver apps/accounts — bootstrap desse grupo).
GRUPO_GESTAO_RV = "Gestao RV"

# ---------------------------------------------------------------------------
# Caminho do projeto legado (motor_calculo/: rv/, config.py, main.py) —
# reaproveitado sem alteração pelo apps/calculo/services.py via subprocess.
# ---------------------------------------------------------------------------
LEGACY_PYTHON_EXECUTABLE = os.environ.get("PYTHON_EXECUTABLE", "python")
LEGACY_MAIN_SCRIPT = MOTOR_CALCULO_DIR / "main.py"
