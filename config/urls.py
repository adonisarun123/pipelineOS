from pathlib import Path

from django.http import Http404, HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def spa(request):
    """Serve the built SPA (single-server deploys). Vercel serves it in prod-split."""
    index = _DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend not built. Run: cd frontend && npm install && npm run build")
    return HttpResponse(index.read_text(), content_type="text/html")


urlpatterns = [
    path("api/v1/", include("api.urls")),
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": _DIST / "assets"}),
    path("", spa),
]
