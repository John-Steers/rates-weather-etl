from datetime import date
from app.main import synthetic_fx

def test_fx_fallback_is_labelled_and_repeatable():
    rows=synthetic_fx(date(2026,1,1),date(2026,1,2))
    assert len(rows)==6
    assert all(row[4] is True for row in rows)
