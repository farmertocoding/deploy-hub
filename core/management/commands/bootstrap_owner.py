"""Create the first persisted owner membership for a workspace."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Workspace, WorkspaceMembership, default_workspace


class Command(BaseCommand):
    help = "Create exactly one persisted owner membership for a workspace."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--workspace", default="default")

    def handle(self, *args, **options):
        username = options["username"]
        slug = options["workspace"] or "default"
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"user {username!r} does not exist") from exc
        with transaction.atomic():
            if slug == "default":
                workspace = default_workspace()
            else:
                try:
                    workspace = Workspace.objects.select_for_update().get(slug=slug)
                except Workspace.DoesNotExist as exc:
                    raise CommandError(f"workspace {slug!r} does not exist") from exc
            owners = WorkspaceMembership.objects.select_for_update().filter(
                workspace=workspace, role="owner",
            )
            if owners.filter(user=user).exists():
                self.stdout.write(f"{username} is already owner of {workspace.slug}")
                return
            if owners.exists():
                raise CommandError(f"workspace {workspace.slug!r} already has an owner")
            WorkspaceMembership.objects.create(
                workspace=workspace, user=user, role="owner",
            )
        self.stdout.write(f"created owner membership for {username} on {workspace.slug}")
