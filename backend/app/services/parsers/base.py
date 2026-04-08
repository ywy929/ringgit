from abc import ABC, abstractmethod
from typing import TypedDict


class ParsedTransaction(TypedDict):
    date: str          # YYYY-MM-DD
    description: str   # Raw description text
    amount: float      # Always positive
    type: str          # "debit" or "credit"


class BaseParser(ABC):
    @abstractmethod
    def can_parse(self, text: str) -> bool:
        ...

    @abstractmethod
    def parse(self, text: str) -> list[ParsedTransaction]:
        ...

    @abstractmethod
    def extract_period_month(self, text: str) -> str:
        ...

    @property
    @abstractmethod
    def bank_id(self) -> str:
        ...
