from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Map service-layer Django ValidationErrors to DRF 400s (no stack traces to users)."""
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.messages)
    return drf_exception_handler(exc, context)
