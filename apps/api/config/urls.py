from allauth.headless.constants import Client
from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import CooldownResendLoginCodeView, MeView
from core import views as core_views
from jobs import views as job_views
from orgs import views as org_views
from projects import views as project_views

router = DefaultRouter(trailing_slash=True)
router.register("organizations", org_views.OrganizationViewSet, basename="organization")
router.register("customers", project_views.CustomerViewSet, basename="customer")
router.register("projects", project_views.ProjectViewSet, basename="project")
router.register("parts", project_views.PartViewSet, basename="part")
router.register("revisions", project_views.RevisionViewSet, basename="revision")
router.register("jobs", job_views.JobViewSet, basename="job")

members = org_views.MemberViewSet
invitations = org_views.InvitationViewSet

api_v1 = [
    path("csrf/", core_views.csrf),
    path("version/", core_views.version),
    path("me/", MeView.as_view()),
    path("organizations/<uuid:org_pk>/members/",
         members.as_view({"get": "list"}), name="org-members"),
    path("organizations/<uuid:org_pk>/members/<uuid:pk>/",
         members.as_view({"patch": "update", "delete": "destroy"}), name="org-member"),
    path("organizations/<uuid:org_pk>/invitations/",
         invitations.as_view({"get": "list", "post": "create"}), name="org-invitations"),
    path("organizations/<uuid:org_pk>/invitations/<uuid:pk>/",
         invitations.as_view({"delete": "destroy"}), name="org-invitation"),
    path("organizations/<uuid:org_pk>/invitations/<uuid:pk>/resend/",
         invitations.as_view({"post": "resend"}), name="org-invitation-resend"),
    path("organizations/<uuid:org_pk>/audit/", core_views.AuditEventsView.as_view()),
    path("organizations/<uuid:org_pk>/benchmark/", job_views.BenchmarkView.as_view()),
    path("invitations/<str:token>/", org_views.InvitationPreviewView.as_view()),
    path("invitations/<str:token>/accept/", org_views.InvitationAcceptView.as_view()),
    path("revisions/<uuid:pk>/jobs/", job_views.RevisionJobsView.as_view()),
    path("files/<uuid:pk>/", project_views.SourceFileView.as_view()),
    path("files/<uuid:pk>/download/", project_views.SourceFileDownloadView.as_view()),
    path("artifacts/", project_views.ArtifactListView.as_view()),
    path("artifacts/<uuid:pk>/download/", project_views.ArtifactDownloadView.as_view()),
    path("search/", project_views.SearchView.as_view()),
    path("system/health/", job_views.SystemHealthView.as_view()),
    path("admin/users/", org_views.AdminUserView.as_view()),
    path("admin/users/<uuid:user_id>/<str:operation>/", org_views.AdminUserView.as_view()),
    path("", include(router.urls)),
]


def admin_login(request):
    """Admin uses the same email-code session as the app (no admin password)."""
    return redirect(f"{settings.PUBLIC_URL}/login?next=/admin/")


admin.site.login = admin_login
admin.site.site_header = f"{settings.PRODUCT_NAME} administration"

urlpatterns = [
    path("healthz", core_views.healthz),
    path("readyz", core_views.readyz),
    # Wrap allauth's resend endpoint with a 60-second cooldown (must precede allauth's URLs).
    path("_allauth/browser/v1/auth/code/resend",
         CooldownResendLoginCodeView.as_api_view(client=Client.BROWSER)),
    path("_allauth/", include("allauth.headless.urls")),
    path("api/v1/", include(api_v1)),
    path("admin/", admin.site.urls),
]
