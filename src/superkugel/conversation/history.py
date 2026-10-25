"""Kurzzeitgedächtnis: die letzten Wortwechsel, begrenzt nach Anzahl und Zeichen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class History:
    turns: list[dict[str, str]] = field(default_factory=list)  # {"role": "user"|"assistant", "content": str}

    @classmethod
    def from_attributes(cls, data: Any) -> History:
        if not isinstance(data, list):
            return cls()
        clean = [
            {"role": t["role"], "content": str(t["content"])[:2000]}
            for t in data
            if isinstance(t, dict) and t.get("role") in ("user", "assistant") and t.get("content")
        ]
        return cls(clean)

    def add(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})

    def trimmed(self, max_turns: int, max_chars: int) -> History:
        """Behält die jüngsten Nachrichten. Ein 'Turn' = Frage + Antwort = 2 Nachrichten."""
        turns = self.turns[-max_turns * 2:]
        while turns and sum(len(t["content"]) for t in turns) > max_chars:
            turns = turns[1:]
        # Der Verlauf soll mit einer Nutzerfrage beginnen.
        while turns and turns[0]["role"] != "user":
            turns = turns[1:]
        return History(list(turns))

    def to_attributes(self) -> list[dict[str, str]]:
        return list(self.turns)

    def as_input(self, new_user_text: str) -> list[dict[str, str]]:
        return [*self.turns, {"role": "user", "content": new_user_text}]
