from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("pipelines", views.PipelineViewSet, basename="pipeline")
router.register("deals", views.DealViewSet, basename="deal")
router.register("activities", views.ActivityViewSet, basename="activity")
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register("people", views.PersonViewSet, basename="person")
router.register("leads", views.LeadViewSet, basename="lead")
router.register("lead-sources", views.LeadSourceViewSet, basename="leadsource")
router.register("activity-types", views.ActivityTypeViewSet, basename="activitytype")
router.register("custom-fields", views.CustomFieldDefViewSet, basename="customfield")
router.register("audit", views.AuditLogViewSet, basename="audit")
router.register("saved-views", views.SavedViewViewSet, basename="savedview")
router.register("users", views.UserViewSet, basename="user")
router.register("products", views.ProductViewSet, basename="product")
router.register("stages", views.StageViewSet, basename="stage")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("files", views.FileAttachmentViewSet, basename="file")
router.register("webhooks", views.WebhookSubscriptionViewSet, basename="webhook")
router.register("lost-reasons", views.LostReasonViewSet, basename="lostreason")

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("search/", views.SearchView.as_view(), name="search"),
    path("import/people/", views.ImportView.as_view(), name="import-people"),
    path("email-account/", views.EmailAccountView.as_view(), name="email-account"),
] + router.urls
