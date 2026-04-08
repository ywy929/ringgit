import hashlib
from pathlib import Path

from app.services.parser_registry import ParserRegistry

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt").read_text()


def test_detect_bank_maybank():
    registry = ParserRegistry()
    parser = registry.detect_bank(SAMPLE_TEXT)
    assert parser is not None
    assert parser.bank_id == "maybank"


def test_detect_bank_unknown():
    registry = ParserRegistry()
    parser = registry.detect_bank("Some random text with no bank markers")
    assert parser is None


def test_compute_file_hash():
    registry = ParserRegistry()
    content = b"test pdf content"
    expected = hashlib.sha256(content).hexdigest()
    assert registry.compute_file_hash(content) == expected
