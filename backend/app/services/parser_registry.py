import hashlib

from app.services.parsers.base import BaseParser
from app.services.parsers.maybank import MaybankParser


class ParserRegistry:
    def __init__(self):
        self.parsers: list[BaseParser] = [
            MaybankParser(),
        ]

    def detect_bank(self, text: str) -> BaseParser | None:
        for parser in self.parsers:
            if parser.can_parse(text):
                return parser
        return None

    def compute_file_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
