from django.urls import path

from . import views

app_name = "cricket_nepal"

urlpatterns = [
    path("", views.home, name="home"),
]
