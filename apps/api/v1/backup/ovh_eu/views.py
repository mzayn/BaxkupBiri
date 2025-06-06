import arrow
import pytz
from django.db.models import Q
from django.utils.timezone import get_current_timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework_datatables.filters import DatatablesFilterBackend
from rest_framework.response import Response
from apps.console.api.v1.backup.ovh_eu.filters import CoreOVHEUBackupFilter
from apps.console.api.v1.backup.ovh_eu.permissions import (
    CoreOVHEUBackupViewPermissions,
)
from apps.console.api.v1.backup.ovh_eu.serializers import CoreOVHEUBackupSerializer
from apps.console.api.v1.utils.api_filters import DateRangeFilter
from apps.console.api.v1.utils.api_helpers import get_start_end_of_previous_day
from apps.console.backup.models import CoreOVHEUBackup
from apps.console.node.models import CoreNode
from rest_framework import status


class CoreOVHEUBackupView(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, CoreOVHEUBackupViewPermissions)
    serializer_class = CoreOVHEUBackupSerializer
    all_fields = [f.name for f in CoreOVHEUBackup._meta.get_fields()]
    filter_backends = [
        DjangoFilterBackend,
        DatatablesFilterBackend,
        SearchFilter,
        DateRangeFilter,
    ]
    filterset_class = CoreOVHEUBackupFilter
    search_fields = all_fields

    def get_queryset(self):
        member = self.request.user.member
        query = Q(ovh_eu__node__connection__account=member.get_current_account())
        query &= ~Q(ovh_eu__node__status=CoreNode.Status.DELETE_REQUESTED)
        query &= ~Q(status=CoreOVHEUBackup.Status.DELETE_REQUESTED)
        if self.request.query_params.get("node"):
            query &= Q(ovh_eu__node__id=self.request.query_params.get("node"))
        queryset = CoreOVHEUBackup.objects.filter(query)
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT, data={})

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.cancel()
        return Response(status=status.HTTP_202_ACCEPTED, data={})

    @action(detail=False)
    def highcharts(self, request):
        graph = {"categories": [], "series": []}
        timezone = str(get_current_timezone())
        timezone = pytz.timezone(timezone)

        start_time = arrow.get(get_start_end_of_previous_day(days=30)["start_time"])
        end_time = arrow.get(get_start_end_of_previous_day(days=0)["start_time"])

        temp_data = []
        for r in arrow.Arrow.span_range("day", start_time.astimezone(timezone), end_time.astimezone(timezone)):
            backup_count = self.get_queryset().filter(
                created__gte=r[0].datetime,
                created__lte=r[1].datetime,
            ).count()

            temp_data.append(backup_count)

        graph["series"].append(
            {
                "name": "OVH-EU",
                "data": temp_data,
                "visible": True,
            }
        )

        # we need labels for the days.
        for r in arrow.Arrow.span_range("day", start_time, end_time):
            graph["categories"].append(r[0].format("MM/DD/YY"))

        return Response(graph)
