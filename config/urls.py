from pathlib import Path

from django.http import HttpResponse
from django.urls import include, path

_SPA = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def spa(request):
    """Serve the SPA raw — the Django template engine must not touch its JS."""
    return HttpResponse(_SPA.read_text(), content_type="text/html")


urlpatterns = [
    path("api/v1/", include("api.urls")),
    path("", spa),
]
