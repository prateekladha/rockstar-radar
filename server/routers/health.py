"""Liveness/health probe for uptime monitoring and load-balancer checks.

Deliberately unauthenticated and minimal: returns a constant status string only
(no build info, versions, identifiers or DB access), so it can be probed cheaply
and frequently without exposing anything.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix='/api', tags=['health'])


@router.get('/health')
def health():
    return {'status': 'ok'}
