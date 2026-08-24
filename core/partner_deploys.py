"""D4 port: Manifest/Deployment live in deploys. Core never imports them.

Wired once from deploys.apps.DeploysConfig.ready(), the same arrow as
core.events / realtime.apps.ready(). Unwired calls fail loud.
"""

_store = None


class PartnerDeployStore:
    def get_deployment(self, partner, deployment_id):
        raise NotImplementedError

    def find_by_job_id(self, partner, job_id):
        raise NotImplementedError

    def create_queued(self, site, body):
        raise NotImplementedError

    def count_since(self, partner, since, site=None):
        raise NotImplementedError


def register_store(store):
    global _store
    _store = store


def _require():
    if _store is None:
        raise RuntimeError(
            "partner deploy store not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.partner_deploys.register_store()"
        )
    return _store


def store():
    return _require()
