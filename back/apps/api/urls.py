from django.urls import path

from apps.api import views

urlpatterns = [
    path('ranking/', views.ranking),
]
