import logging

from django.db import connection
from django.db.utils import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_check(request):
    try:
        connection.ensure_connection()
    except DatabaseError:
        logger.exception("Health check could not connect to the database.")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
