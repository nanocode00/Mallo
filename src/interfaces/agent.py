from typing import Protocol

from domain.models import Cart, OrderCommand, OrderResult


class Agent(Protocol):
    def execute(self, commands: list[OrderCommand], cart: Cart) -> OrderResult: ...

    def reset_session(self) -> None: ...
