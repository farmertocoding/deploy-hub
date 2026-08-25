"""D4 port: overflow deploy lives in deploys. Core never imports it.

Wired once from deploys.apps.DeploysConfig.ready(), the same arrow as
core.partner_deploys / realtime.apps.ready(). Unwired calls fail loud.
"""

_impl = None


class OverflowDeployError(Exception):
    """Propose-gate or overflow-target refuse. No Deployment on the gate path."""


def register_deploy(impl):
    global _impl
    _impl = impl


def deploy(*args, **kwargs):
    if _impl is None:
        raise RuntimeError(
            "overflow deploy not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.overflow_deploys.register_deploy()"
        )
    return _impl(*args, **kwargs)
