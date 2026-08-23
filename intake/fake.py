"""T1 Fake intake state: public keys, counters, outbox. No webhook secret."""
from intake.outbox import Outbox


class FakeIntake:
    def __init__(self):
        self.public_keys = {}
        self.counters = {}
        self.outbox = Outbox()
        self.sites = {}
        self.deployments = {}
        self.domains = {}
        self._n = 0

    def register_public_key(self, key_id, public_key):
        self.public_keys[key_id] = public_key

    def new_id(self, prefix):
        self._n += 1
        return f"{prefix}_{self._n}"
