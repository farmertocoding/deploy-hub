"""In-memory mesh outbox. Not mounted on the public listener."""


class Outbox:
    def __init__(self):
        self._items = []

    def put(self, job):
        self._items.append(job)

    def snapshot(self):
        return list(self._items)

    def ack(self, job_id):
        self._items = [item for item in self._items if item.get("id") != job_id]

    def plant_git_push(self, git_url, ref, sha, *, job_id=None):
        """T1 Fake plant. Not a public webhook; no secret required."""
        item = {
            "id": job_id or f"git-push-{len(self._items) + 1}",
            "type": "git-push",
            "git_url": git_url,
            "ref": ref,
            "sha": sha,
        }
        self.put(item)
        return item
