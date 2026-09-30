from django.urls import path

from apps.api import views

urlpatterns = [
    path('ranking/', views.ranking),
    path('pokemon/', views.pokemon_list),
    path('pokemon/<str:sid>/', views.pokemon_detail),
]
