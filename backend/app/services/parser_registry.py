import hashlib

from app.services.parsers.base import BaseParser
from app.services.parsers.maybank import MaybankParser
from app.services.parsers.cimb import CIMBParser
from app.services.parsers.public_bank import PublicBankParser
from app.services.parsers.hong_leong import HongLeongParser
from app.services.parsers.tng import TnGParser
from app.services.parsers.aeon import AEONParser


class ParserRegistry:
    def __init__(self):
        self.parsers: list[BaseParser] = [
            MaybankParser(), CIMBParser(), PublicBankParser(),
            HongLeongParser(), TnGParser(), AEONParser(),
        ]

    def detect_bank(self, text: str) -> BaseParser | None:
        for parser in self.parsers:
            if parser.can_parse(text):
                return parser
        return None

    def compute_file_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
