class FakeClock:
    """Deterministic clock so a "wait 1.5s" or "idle overnight" costs nothing."""

    def __init__(self, start: float = 0.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
