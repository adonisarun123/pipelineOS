from rest_framework.pagination import CursorPagination


class DefaultCursorPagination(CursorPagination):
    ordering = "-id"
    page_size = 50
