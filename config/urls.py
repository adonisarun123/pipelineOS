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


def _dist_file(name: str, content_type: str):
    def view(request):
        f = _DIST / name
        if not f.exists():
            raise Http404
        return HttpResponse(f.read_bytes(), content_type=content_type)

    return view


urlpatterns = [
    path("api/v1/", include("api.urls")),
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": _DIST / "assets"}),
    path("sw.js", _dist_file("sw.js", "application/javascript")),
    path("manifest.webmanifest", _dist_file("manifest.webmanifest",
                                            "application/manifest+json")),
    path("icon.svg", _dist_file("icon.svg", "image/svg+xml")),
    path("", spa),
]
