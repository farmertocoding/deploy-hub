"""D4 port: overflow deploy lives in deploys. Core never imports it.

Wired once from deploys.apps.DeploysConfig.ready(), the same arrow as
core.partner_deploys / realtime.apps.ready(). Unwired calls fail loud.
"""

_impl = None
_join = None
_scale_in = None


class OverflowDeployError(Exception):
    """Propose-gate or overflow-target refuse. No Deployment on the gate path."""


def register_deploy(impl):
    global _impl
    _impl = impl


def register_join(impl):
    global _join
    _join = impl


def register_scale_in(impl):
    global _scale_in
    _scale_in = impl


def deploy(*args, **kwargs):
    if _impl is None:
        raise RuntimeError(
            "overflow deploy not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.overflow_deploys.register_deploy()"
        )
    return _impl(*args, **kwargs)


def join(*args, **kwargs):
    if _join is None:
        raise RuntimeError(
            "overflow join not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.overflow_deploys.register_join()"
        )
    return _join(*args, **kwargs)


def scale_in(*args, **kwargs):
    if _scale_in is None:
        raise RuntimeError(
            "overflow scale-in not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.overflow_deploys.register_scale_in()"
        )
    return _scale_in(*args, **kwargs)
