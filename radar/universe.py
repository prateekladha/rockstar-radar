"""Configurable trading universe — pick any NSE index (and thereby any cap).

The 'cap' dimension is expressed through the index itself: Nifty 50/100 ≈ large cap,
Nifty Midcap 150 ≈ mid cap, Nifty Smallcap 250 ≈ small cap. Each maps to its official
NSE constituent CSV, which the scanner downloads (same mechanism as the existing NIFTY 500).
"""
from __future__ import annotations

_BASE = 'https://niftyindices.com/IndexConstituent/'

INDICES = {
    'nifty50': {'label': 'Nifty 50', 'cap': 'Large cap', 'file': 'ind_nifty50list.csv'},
    'nifty100': {'label': 'Nifty 100', 'cap': 'Large cap', 'file': 'ind_nifty100list.csv'},
    'nifty200': {'label': 'Nifty 200', 'cap': 'Large / mid', 'file': 'ind_nifty200list.csv'},
    'nifty500': {'label': 'Nifty 500', 'cap': 'All caps', 'file': 'ind_nifty500list.csv'},
    'niftynext50': {'label': 'Nifty Next 50', 'cap': 'Large cap', 'file': 'ind_niftynext50list.csv'},
    'niftymidcap150': {'label': 'Nifty Midcap 150', 'cap': 'Mid cap', 'file': 'ind_niftymidcap150list.csv'},
    'niftysmallcap250': {'label': 'Nifty Smallcap 250', 'cap': 'Small cap', 'file': 'ind_niftysmallcap250list.csv'},
    'niftybank': {'label': 'Nifty Bank', 'cap': 'Sector', 'file': 'ind_niftybanklist.csv'},
}
DEFAULT = 'nifty500'


def catalog() -> list[dict]:
    return [{'id': k, 'label': v['label'], 'cap': v['cap']} for k, v in INDICES.items()]


def is_valid(index_id: str) -> bool:
    return index_id in INDICES


def url_for(index_id: str) -> str:
    meta = INDICES.get(index_id or DEFAULT, INDICES[DEFAULT])
    return _BASE + meta['file']


def label_for(index_id: str) -> str:
    return INDICES.get(index_id or DEFAULT, INDICES[DEFAULT])['label']
