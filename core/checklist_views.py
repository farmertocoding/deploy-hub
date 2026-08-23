"""GET /api/v1/first-run/ — table-backed checklist snapshot.

seq is the findings counter (D-045). Completion is derived fleet state, not
a new realtime topic. core/views.py stays untouched (auth custody).
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.checklist import ITEM_IDS, first_run_progress
from core.findings import findings_seq


class FirstRunItemSerializer(serializers.Serializer):
    id = serializers.ChoiceField(choices=ITEM_IDS)
    applicable = serializers.BooleanField()
    done = serializers.BooleanField()


class FirstRunProgressSerializer(serializers.Serializer):
    owns_home = serializers.BooleanField()
    items = FirstRunItemSerializer(many=True)


class FirstRunSnapshotSerializer(serializers.Serializer):
    seq = serializers.IntegerField()
    data = FirstRunProgressSerializer()


class FirstRunView(APIView):
    @extend_schema(responses={200: FirstRunSnapshotSerializer})
    def get(self, request):
        seq = findings_seq()
        return Response({"seq": seq, "data": first_run_progress()})
