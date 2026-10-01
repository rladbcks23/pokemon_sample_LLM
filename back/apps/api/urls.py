from django.urls import path

from apps.api import views

urlpatterns = [
    path('ranking/', views.ranking),
    path('pokemon/', views.pokemon_list),
    path('pokemon/<str:sid>/', views.pokemon_detail),
    path('teams/', views.team_list),
    path('teams/<int:pk>/', views.team_detail),
    path('samples/', views.sample_list),
    path('options/', views.options),
    path('validate/', views.validate_set),
]
