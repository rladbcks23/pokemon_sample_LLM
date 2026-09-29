from django.apps import AppConfig


class ApiConfig(AppConfig):
    """프론트(Vue)용 조회 API. 모델은 dex, meta 앱에 있고 여기는 시리얼라이저와 뷰만 둔다."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.api'
    label = 'api'
