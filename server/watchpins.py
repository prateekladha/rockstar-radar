"""Per-user manual watchlist pins.

A pin is a stock the user adds by hand so it is (a) priority-scanned by their feed and (b) always
surfaced at the top of their smart watchlist, ahead of the auto-ranked opportunities. Pins persist
day to day (stored on the per-user Watchlist row) — set them once and they ride every session.

Storage reuses the existing per-user Watchlist.symbols_text (newline-separated canonical FYERS
tickers, e.g. ``NSE:RELIANCE-EQ``). Canonicalisation + validation is shared with the scanner's
morning-pin logic so a pin and a scanned symbol are always the same string.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from radar.selecting import SelectionError, normalize_morning_symbol

from .models import Watchlist

# FYERS Standard data plan caps a live session at 100 symbols; keep manual pins well under that so
# they never crowd out the auto universe.
MAX_PINS = 25


class PinError(ValueError):
    pass


def bare(symbol: str) -> str:
    """``NSE:RELIANCE-EQ`` -> ``RELIANCE`` (the ticker the scanner/UI show)."""
    s = (symbol or '').strip().upper()
    if s.startswith('NSE:'):
        s = s[4:]
    for suf in ('-EQ', '-BE'):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def _row(db: Session, user_id: int) -> Watchlist | None:
    return db.query(Watchlist).filter_by(user_id=user_id).first()


def get_pins(db: Session, user_id: int) -> list[str]:
    """The user's pins as canonical FYERS tickers (``NSE:...-EQ``), in the order added."""
    row = _row(db, user_id)
    if not row or not row.symbols_text:
        return []
    out, seen = [], set()
    for tok in row.symbols_text.replace(',', '\n').split('\n'):
        tok = tok.strip()
        if not tok:
            continue
        try:
            canon = normalize_morning_symbol(tok)
        except SelectionError:
            continue
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def _save(db: Session, user_id: int, canon: list[str]) -> None:
    row = _row(db, user_id)
    text = '\n'.join(canon)
    if row is None:
        db.add(Watchlist(user_id=user_id, symbols_text=text))
    else:
        row.symbols_text = text
    db.commit()


def add_pin(db: Session, user_id: int, raw: str) -> list[str]:
    try:
        canon = normalize_morning_symbol(raw or '')
    except SelectionError as e:
        raise PinError(str(e)) from e
    pins = get_pins(db, user_id)
    if canon in pins:
        return pins
    if len(pins) >= MAX_PINS:
        raise PinError(f'You can pin up to {MAX_PINS} stocks. Remove one before adding another.')
    pins.append(canon)
    _save(db, user_id, pins)
    return pins


def remove_pin(db: Session, user_id: int, raw: str) -> list[str]:
    target = bare(raw)
    pins = [p for p in get_pins(db, user_id) if bare(p) != target]
    _save(db, user_id, pins)
    return pins


def pins_env(db: Session, user_id: int) -> str:
    """Comma-joined canonical pins for the scanner subprocess (RADAR_MORNING_PINS)."""
    return ','.join(get_pins(db, user_id))
