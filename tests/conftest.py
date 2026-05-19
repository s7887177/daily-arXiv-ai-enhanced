from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cs_ai_xml() -> bytes:
    return (FIXTURES / "cs.AI_sample.xml").read_bytes()


@pytest.fixture
def cs_cl_xml() -> bytes:
    return (FIXTURES / "cs.CL_sample.xml").read_bytes()
