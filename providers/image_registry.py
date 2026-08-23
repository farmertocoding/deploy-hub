"""ImageRegistry product adapters (D-073).

T1 uses FakeImageRegistry (TLS + auth, split push/pull). A real ECR
client, if one lands, imports boto3 in this module only — never
providers/registry.py. Live ECR is a Joseph interrupt; unconfigured
construction fail-closes rather than returning an open registry.
"""


class ImageRegistryError(RuntimeError):
    """Construction or registry call failed. Never carries a password."""


def build(desired=None):
    """Construct a product ImageRegistry. Live ECR is not enabled.

    image_registry_for maps default ship_mode=load to None before this
    runs. ship_mode=registry without a product adapter is fail-closed,
    not a constructed open registry.
    """
    raise ImageRegistryError(
        "image registry is not configured; docker load remains the default"
    )
