"""Super admin URLs: mounted at /api/v1/superadmin/ in config/urls.py."""
from rest_framework.routers import SimpleRouter

from . import views

app_name = "superadmin"

# SimpleRouter: JSON only, no browsable API-root page.
router = SimpleRouter()
router.register("businesses", views.BusinessViewSet, basename="superadmin-business")
router.register("users", views.PlatformUserViewSet, basename="superadmin-user")

urlpatterns = router.urls  # businesses/, businesses/<pk>/status/, users/, users/<pk>/
