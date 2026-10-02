from django.urls import path

from apps.api import speed, views

urlpatterns = [
    path('ranking/', views.ranking),
    path('pokemon/', views.pokemon_list),
    path('pokemon/<str:sid>/', views.pokemon_detail),
    path('teams/', views.team_list),
    path('teams/<int:pk>/', views.team_detail),
    path('samples/', views.sample_list),
    path('speed/', speed.speed_tiers),
    path('options/', views.options),
    path('validate/', views.validate_set),
]
