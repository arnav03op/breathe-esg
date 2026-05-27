"""
URL configuration for the emissions app.

All routes are prefixed with /api/ when included in the project root.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from emissions.views import EmissionRowViewSet, IngestionLogViewSet, UploadView

router = DefaultRouter()
router.register(r"emissions", EmissionRowViewSet, basename="emission-row")
router.register(r"ingestion-logs", IngestionLogViewSet, basename="ingestion-log")
router.register(r"upload", UploadView, basename="upload")

urlpatterns = [
    path("", include(router.urls)),
]
