"""chorus.ledger.repos._base — the shared JSON + invariant helpers (spec 01)."""

from __future__ import annotations

import pytest

from chorus.ledger.repos._base import (
    LedgerInvariantError,
    loads_dict,
    loads_list,
    require_persisted,
)

pytestmark = pytest.mark.unit


class TestLoadsDict:
    def test_parses_an_object(self) -> None:
        assert loads_dict('{"a": 1}') == {"a": 1}

    def test_none_and_empty_and_non_object_default_to_empty(self) -> None:
        assert loads_dict(None) == {}
        assert loads_dict("") == {}
        assert loads_dict("[1, 2]") == {}  # a JSON array is not an object


class TestLoadsList:
    def test_parses_an_array(self) -> None:
        assert loads_list("[1, 2]") == [1, 2]

    def test_none_and_empty_and_non_array_default_to_empty(self) -> None:
        assert loads_list(None) == []
        assert loads_list("") == []
        assert loads_list('{"a": 1}') == []  # a JSON object is not an array


class TestRequirePersisted:
    def test_returns_a_present_value(self) -> None:
        assert require_persisted("row", "id_1") == "row"

    def test_raises_on_a_missing_row(self) -> None:
        with pytest.raises(LedgerInvariantError, match="id_1"):
            require_persisted(None, "id_1")
