"""Outbound ports so the kernel does not import deploys/scanner/wizard."""
from rest_framework import status
from rest_framework.response import Response


class FleetRefuse(Exception):
    def __init__(self, field, message):
        super().__init__(message)
        self.response = Response(
            {"errors": {field: [{"code": "conflict", "message": message, "hint": ""}]}},
            status=status.HTTP_409_CONFLICT,
        )


class DeploysPort:
    Deployment = None
    Manifest = None
    release_deploy_locks = None


class WizardPort:
    create_project = None
    ProjectCreateSerializer = None
    project_row_body = None


deploys = DeploysPort()
wizard = WizardPort()
TOPIC_HANDLERS = {}


def register_deploys(*, Deployment, Manifest, release_deploy_locks):
    deploys.Deployment = Deployment
    deploys.Manifest = Manifest
    deploys.release_deploy_locks = release_deploy_locks


def register_wizard(*, create_project, ProjectCreateSerializer, project_row_body):
    wizard.create_project = create_project
    wizard.ProjectCreateSerializer = ProjectCreateSerializer
    wizard.project_row_body = project_row_body


def register_topic(topic, handler):
    TOPIC_HANDLERS[topic] = handler
