"""
DRF views for the emissions app.

Provides:
    - EmissionRowViewSet: list, retrieve, partial-update, plus custom actions
      for approve, flag, lock, and bulk-approve.
    - IngestionLogViewSet: read-only list/detail of ingestion logs.
    - AuditLogViewSet: read-only list of audit entries per emission row.
    - UploadView: file-upload endpoints for each source type.
"""

from django.utils import timezone
from django_filters import rest_framework as django_filters
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from emissions.models import (
    AuditLog,
    ClientCompany,
    DataIngestionLog,
    UniversalEmissionRow,
)
from emissions.serializers import (
    AuditLogSerializer,
    DataIngestionLogSerializer,
    EmissionRowListSerializer,
    EmissionRowSerializer,
)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
class EmissionRowFilter(django_filters.FilterSet):
    """
    Supports query params like:
        ?status=PENDING
        ?status=FLAGGED
        ?scope_category=SCOPE_1
        ?source_type=SAP
        ?client=1
        ?ingested_after=2024-01-01
        ?ingested_before=2024-12-31
    """

    source_type = django_filters.CharFilter(
        field_name="ingestion_log__source_type", lookup_expr="exact"
    )
    ingested_after = django_filters.DateTimeFilter(
        field_name="ingested_at", lookup_expr="gte"
    )
    ingested_before = django_filters.DateTimeFilter(
        field_name="ingested_at", lookup_expr="lte"
    )

    class Meta:
        model = UniversalEmissionRow
        fields = [
            "status",
            "scope_category",
            "client",
            "source_type",
            "sub_category",
            "facility_code",
        ]


# ---------------------------------------------------------------------------
# EmissionRowViewSet
# ---------------------------------------------------------------------------
class EmissionRowViewSet(viewsets.ModelViewSet):
    """
    CRUD + custom workflow actions for emission rows.

    List:     GET    /api/emissions/
    Detail:   GET    /api/emissions/{id}/
    Update:   PATCH  /api/emissions/{id}/
    Approve:  POST   /api/emissions/{id}/approve/
    Flag:     POST   /api/emissions/{id}/flag/
    Lock:     POST   /api/emissions/{id}/lock/
    Bulk:     POST   /api/emissions/bulk-approve/
    History:  GET    /api/emissions/{id}/history/
    Summary:  GET    /api/emissions/summary/
    """

    queryset = (
        UniversalEmissionRow.objects
        .select_related("client", "ingestion_log", "ingestion_log__client",
                        "approved_by", "ingestion_log__uploaded_by")
        .order_by("-ingested_at")
    )
    filterset_class = EmissionRowFilter
    search_fields = ["facility_name", "facility_code", "sub_category", "error_notes"]
    ordering_fields = [
        "ingested_at", "co2e_kg", "normalized_value", "status",
        "scope_category", "activity_start_date",
    ]

    def get_serializer_class(self):
        if self.action == "list":
            return EmissionRowListSerializer
        return EmissionRowSerializer

    # ---- Helper: create an audit log entry ----
    def _audit(self, row, old_status, new_status, user, note=""):
        AuditLog.objects.create(
            emission_row=row,
            changed_by=user,
            old_status=old_status,
            new_status=new_status,
            note=note,
        )

    # ---- Helper: transition status ----
    def _transition(self, request, pk, allowed_from, new_status, note_field="note"):
        row = self.get_object()
        if row.status not in allowed_from:
            return Response(
                {
                    "error": (
                        f"Cannot transition from '{row.status}' to '{new_status}'. "
                        f"Allowed source states: {allowed_from}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = row.status
        row.status = new_status

        user = request.user if request.user.is_authenticated else None

        # Set approval metadata if transitioning to APPROVED.
        if new_status == "APPROVED":
            row.approved_by = user
            row.approved_at = timezone.now()

        row.save()
        note = request.data.get(note_field, "")
        self._audit(row, old_status, new_status, user, note)

        serializer = EmissionRowSerializer(row)
        return Response(serializer.data)

    # ---- Custom actions ----

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """PENDING or FLAGGED → APPROVED. Sets approved_by and approved_at."""
        return self._transition(
            request, pk,
            allowed_from=["PENDING", "FLAGGED"],
            new_status="APPROVED",
        )

    @action(detail=True, methods=["post"])
    def flag(self, request, pk=None):
        """PENDING → FLAGGED. Requires a note explaining why."""
        note = request.data.get("note", "")
        if not note:
            return Response(
                {"error": "A note is required when flagging a row."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._transition(
            request, pk,
            allowed_from=["PENDING"],
            new_status="FLAGGED",
        )

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        """APPROVED → LOCKED. Freezes the row for audit."""
        return self._transition(
            request, pk,
            allowed_from=["APPROVED"],
            new_status="LOCKED",
        )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        """Return the full audit trail for a specific emission row."""
        row = self.get_object()
        logs = row.audit_logs.select_related("changed_by").order_by("-changed_at")
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="bulk-approve")
    def bulk_approve(self, request):
        """
        Approve multiple rows at once.
        Body: {"ids": [1, 2, 3], "note": "Batch approval"}
        """
        ids = request.data.get("ids", [])
        if not ids:
            return Response(
                {"error": "Provide a list of row IDs in 'ids'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = request.data.get("note", "Bulk approval")
        rows = UniversalEmissionRow.objects.filter(
            pk__in=ids, status__in=["PENDING", "FLAGGED"]
        )
        approved_ids = []
        user = request.user if request.user.is_authenticated else None
        for row in rows:
            old = row.status
            row.status = "APPROVED"
            row.approved_by = user
            row.approved_at = timezone.now()
            row.save()
            self._audit(row, old, "APPROVED", user, note)
            approved_ids.append(row.pk)

        return Response({
            "approved": approved_ids,
            "count": len(approved_ids),
        })

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Dashboard summary stats:
            - total rows, by status, by scope, by source type
        """
        from django.db.models import Count, Sum

        # Use unfiltered base queryset for summary — don't apply list filters.
        # Clear ordering (.order_by()) so Django doesn't include ORDER BY
        # fields in GROUP BY, which would break aggregation.
        qs = UniversalEmissionRow.objects.order_by()

        status_counts = dict(
            qs.values("status")
            .annotate(n=Count("id"))
            .values_list("status", "n")
        )
        scope_counts = dict(
            qs.values("scope_category")
            .annotate(n=Count("id"))
            .values_list("scope_category", "n")
        )
        source_counts = dict(
            qs.values("ingestion_log__source_type")
            .annotate(n=Count("id"))
            .values_list("ingestion_log__source_type", "n")
        )
        total_co2e = qs.aggregate(total=Sum("co2e_kg"))["total"]

        return Response({
            "total_rows": qs.count(),
            "total_co2e_kg": total_co2e,
            "by_status": status_counts,
            "by_scope": scope_counts,
            "by_source": source_counts,
        })


# ---------------------------------------------------------------------------
# IngestionLogViewSet (read-only)
# ---------------------------------------------------------------------------
class IngestionLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only list/detail of ingestion logs."""

    queryset = (
        DataIngestionLog.objects
        .select_related("client", "uploaded_by")
        .order_by("-upload_timestamp")
    )
    serializer_class = DataIngestionLogSerializer
    filterset_fields = ["source_type", "status", "client"]


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------
class UploadView(viewsets.ViewSet):
    """
    File upload endpoints that trigger ingestion services.

    POST /api/upload/sap/       — upload SAP CSV
    POST /api/upload/utility/   — upload Utility CSV
    POST /api/upload/travel/    — upload Travel JSON
    """

    parser_classes = [MultiPartParser]

    def _handle_upload(self, request, source_type):
        """Common upload handler."""
        file_obj = request.FILES.get("file")
        company_id = request.data.get("company_id")

        if not file_obj:
            return Response(
                {"error": "No file provided. Send as multipart 'file' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not company_id:
            return Response(
                {"error": "company_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prototype Auto-Seeding: Ensure the requested company exists so 
        # database flushes don't break the frontend's hardcoded uploads.
        ClientCompany.objects.get_or_create(
            pk=company_id, 
            defaults={"name": f"Auto-Created Company {company_id}"}
        )

        # Save uploaded file to a temp location.
        import tempfile
        import os

        suffix = ".json" if source_type == "travel" else ".csv"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir="."
        ) as tmp:
            for chunk in file_obj.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            if source_type == "sap":
                from emissions.services.sap_ingestion import ingest_sap_csv
                result = ingest_sap_csv(tmp_path, int(company_id), request.user.pk)
            elif source_type == "utility":
                from emissions.services.utility_ingestion import ingest_utility_csv
                result = ingest_utility_csv(tmp_path, int(company_id), request.user.pk)
            elif source_type == "travel":
                from emissions.services.travel_ingestion import ingest_travel_json
                result = ingest_travel_json(tmp_path, int(company_id), request.user.pk)
            else:
                return Response(
                    {"error": f"Unknown source type: {source_type}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        finally:
            os.unlink(tmp_path)

        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="sap")
    def upload_sap(self, request):
        return self._handle_upload(request, "sap")

    @action(detail=False, methods=["post"], url_path="utility")
    def upload_utility(self, request):
        return self._handle_upload(request, "utility")

    @action(detail=False, methods=["post"], url_path="travel")
    def upload_travel(self, request):
        return self._handle_upload(request, "travel")
