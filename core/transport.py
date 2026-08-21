"""Transport seam (§A7): every remote effect goes through this interface.

Real SSH (fabric) lands in Phase 2; Phase 0 ships the interface + fakes so every
feature is testable at T1 from its first commit. Injection-safe by construction
(§4.5): argument lists only, never interpolated shell strings.
"""


class Transport:
    """One connection to one target."""

    def run(self, argv, *, timeout=60):
        """Run a command. argv is a list — never a shell string."""
        raise NotImplementedError

    def probe(self, argv, *, timeout=60):
        """Read-only inspect. argv is a list — never a shell string."""
        raise NotImplementedError

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        """Deliver file content via SFTP-equivalent — never heredocs."""
        raise NotImplementedError

    def get(self, remote_path):
        raise NotImplementedError


class CommandResult:
    def __init__(self, argv, exit_code=0, stdout="", stderr=""):
        self.argv = argv
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self):
        return self.exit_code == 0


class FakeTransport(Transport):
    """T1 double: scripted responses keyed by argv[0], records everything."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []  # (kind, payload) tuples — the run-twice test reads this
        self.files = {}
        self.put_modes = {}

    def run(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        self.calls.append(("run", list(argv)))
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        self.calls.append(("probe", list(argv)))
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        self.calls.append(("put", remote_path))
        self.files[remote_path] = local_path_or_bytes
        self.put_modes[remote_path] = mode

    def get(self, remote_path):
        self.calls.append(("get", remote_path))
        return self.files.get(remote_path, b"")

    def mutating_calls(self):
        """Calls that change remote state — must be [] on a second idempotent run (§D6)."""
        return [c for c in self.calls if c[0] in ("run", "put")]


class RecordingTransport(Transport):
    """Wraps a real transport, recording calls for repro bundles (§5 bug-fix automation)."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def run(self, argv, *, timeout=60):
        self.calls.append(("run", list(argv)))
        return self.inner.run(argv, timeout=timeout)

    def probe(self, argv, *, timeout=60):
        self.calls.append(("probe", list(argv)))
        return self.inner.probe(argv, timeout=timeout)

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        self.calls.append(("put", remote_path))
        return self.inner.put(local_path_or_bytes, remote_path, mode=mode)

    def get(self, remote_path):
        self.calls.append(("get", remote_path))
        return self.inner.get(remote_path)

    def mutating_calls(self):
        """Calls that change remote state — must be [] on a second idempotent run (§D6)."""
        return [c for c in self.calls if c[0] in ("run", "put")]
