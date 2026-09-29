from django.apps import AppConfig


class DexConfig(AppConfig):
    """게임 데이터 (레귤레이션별 포켓몬, 기술, 도구, 특성, 배우는 기술 + 타입 상성, 성격)."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.dex'
    label = 'dex'
    verbose_name = '게임 데이터'
