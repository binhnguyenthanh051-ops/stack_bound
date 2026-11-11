"""The one exception type: an analysis error that names what blocked the result (exit code 2)."""


class AnalysisError(Exception):
    """Something the tool could not see or prove. Never a silent zero (ADR-0001 D1)."""

    def __init__(self, messages: list[str] | str):
        self.messages = [messages] if isinstance(messages, str) else list(messages)
        super().__init__("; ".join(self.messages))
