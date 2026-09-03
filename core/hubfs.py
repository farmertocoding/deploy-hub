"""Deploy-writable Hub paths on a target. Never world-writable /tmp (B108)."""

DEFAULT_USER = "deploy"


def hub_root(ssh_user=None):
    return f"/home/{ssh_user or DEFAULT_USER}/.hub"


def hub_join(*parts, ssh_user=None):
    root = hub_root(ssh_user)
    if not parts:
        return root
    pieces = []
    for part in parts:
        text = str(part).replace("\\", "/")
        if any(seg == ".." for seg in text.split("/")):
            raise ValueError("hub path must stay under the hub prefix")
        pieces.append(text.lstrip("/"))
    return root + "/" + "/".join(pieces)


def ssh_user_from(desired_or_target):
    if desired_or_target is None:
        return DEFAULT_USER
    if not isinstance(desired_or_target, dict):
        return getattr(desired_or_target, "ssh_user", None) or DEFAULT_USER
    target = desired_or_target.get("target")
    if target is None:
        site = desired_or_target.get("site")
        target = getattr(site, "primary_target", None) if site is not None else None
    return getattr(target, "ssh_user", None) or DEFAULT_USER


def ensure_hub_dir(transport, ssh_user=None, heartbeat=None):
    """mkdir + chmod 0700 the Hub prefix. Heartbeat around the mutating runs."""
    root = hub_root(ssh_user)
    if heartbeat is not None:
        heartbeat()
    transport.run(["mkdir", "-p", root])
    if heartbeat is not None:
        heartbeat()
    transport.run(["chmod", "700", root])
    return root
