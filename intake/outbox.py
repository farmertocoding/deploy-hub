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
