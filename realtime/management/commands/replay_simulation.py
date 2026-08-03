"""`manage.py replay_simulation` — run the §F8 event replayer (simulation/seed_v0.json)
through the real Channels path. The demo panel's "Watch simulation" button subscribes
to the topics this publishes to.
"""
from django.core.management.base import BaseCommand

from realtime.simulation import replay


class Command(BaseCommand):
    help = "Replay the simulation-mode seed's scripted events through publish() (§F8 v0)."

    def add_arguments(self, parser):
        parser.add_argument("--speed", type=float, default=1.0,
                            help="Time multiplier: 2.0 = twice as fast (default 1.0).")
        parser.add_argument("--loop", type=int, default=1,
                            help="Number of times to replay the script (default 1).")

    def handle(self, *args, **opts):
        total = 0
        for _ in range(opts["loop"]):
            total += replay(speed=opts["speed"])
        self.stdout.write(self.style.SUCCESS(f"replayed {total} scripted events"))
