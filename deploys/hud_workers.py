from core.hud.operations import OperationDispatchError


def enqueue_deployment(operation):
    from deploys.tasks import run_deploy

    try:
        run_deploy.delay(int(operation.object_id))
    except Exception as exc:
        raise OperationDispatchError(str(exc), code="enqueue_failed") from exc
    return {"ok": True, "effect": "deployment_enqueued", "deployment_id": operation.object_id}
