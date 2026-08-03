"""Demo-job API — deliberately trivial; the §4.5 validation pipeline is the deliverable.

Errors block (400, {field: [{code, message, hint}]}); warnings ask
(warning list + confirm_warnings flag). This is the reference implementation
every later form copies.
"""
import uuid

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit

from .authorize import authorize_topic
from .publish import current_seq, topic_history
from .tasks import demo_stream_logs


class DemoJobSerializer(serializers.Serializer):
    name = serializers.RegexField(
        r"^[a-z][a-z0-9-]{1,30}$",
        error_messages={"invalid": "Lowercase letters, digits and dashes; start with a letter."},
    )
    delay = serializers.FloatField(min_value=0.05, max_value=5.0, default=0.5)
    confirm_warnings = serializers.BooleanField(default=False)

    def warnings(self):
        """Legal-but-suspicious input (§4.5): returned first, acknowledged second."""
        out = []
        if self.validated_data["delay"] > 2.0:
            out.append(
                {
                    "field": "delay",
                    "code": "slow_demo",
                    "message": f"A {self.validated_data['delay']}s delay makes the demo crawl.",
                    "hint": "0.5s reads well; continue if you want it slow.",
                }
            )
        return out


def drf_errors_to_contract(errors):
    """DRF error dict → the §4.5 shape: {field: [{code, message, hint}]}."""
    out = {}
    for field, msgs in errors.items():
        out[field] = [
            {"code": getattr(m, "code", "invalid"), "message": str(m), "hint": ""} for m in msgs
        ]
    return out


class DemoJobView(APIView):
    @extend_schema(request=DemoJobSerializer, responses={201: dict})
    def post(self, request):
        ser = DemoJobSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {"errors": drf_errors_to_contract(ser.errors)}, status=status.HTTP_400_BAD_REQUEST
            )
        warnings = ser.warnings()
        if warnings and not ser.validated_data["confirm_warnings"]:
            return Response({"warnings": warnings}, status=status.HTTP_409_CONFLICT)

        job_id = f"{ser.validated_data['name']}-{uuid.uuid4().hex[:6]}"
        demo_stream_logs.delay(job_id, ser.validated_data["delay"])
        audit("demo_job_started", source="api", actor=request.user, job_id=job_id)
        return Response({"job_id": job_id, "topic": f"demo.{job_id}.log"}, status=201)


class TopicSnapshotView(APIView):
    """Snapshot-then-stream (§D7): every snapshot returns {seq, data} from the same counter."""

    def get(self, request, topic):
        # Same choke point as the socket (§D7): snapshot is just the read half of
        # subscribe — an unauthorized topic must fail here exactly as it does there.
        if not authorize_topic(request.user, topic):
            return Response({"detail": "Topic not authorized."}, status=403)
        # data = capped history entries [{seq, event}] for log-style topics (empty
        # for topics without history); panels repaint from it, then stream from seq.
        return Response({"seq": current_seq(topic), "data": topic_history(topic)})
