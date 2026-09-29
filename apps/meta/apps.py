from django.apps import AppConfig


class MetaConfig(AppConfig):
    """메타/파티 데이터 (사용률, 파티, 육성형)."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.meta'
    label = 'meta'
    verbose_name = '메타 / 파티'
