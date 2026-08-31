from core.hud.operations import OperationDispatchError


def enqueue_deployment(operation):
    from deploys.tasks import enqueue_run_deploy

    try:
        enqueue_run_deploy(int(operation.object_id))
    except Exception as exc:
        raise OperationDispatchError(str(exc), code="enqueue_failed") from exc
    return {"ok": True, "effect": "deployment_enqueued", "deployment_id": operation.object_id}
