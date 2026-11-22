"""Tests for the stalled-websocket feed gate that drives alert/display fallback (server.scanners).

Regression for the Friday MARUTI case: a user's own scanner was running with an ok=true health file
but its websocket was stuck reconnecting, so no bars completed and the user got zero confirmations /
alerts while the household's other feed was healthy. `_feed_stalled` detects that by data staleness so
`_feed_for` / `effective_feed` fall back to the household's live feed.
"""
import unittest

try:
    from server.scanners import _feed_stalled
    HAVE = True
except Exception:          # pragma: no cover - server deps (sqlalchemy/fastapi) not installed
    HAVE = False


@unittest.skipUnless(HAVE, 'server deps not installed')
class FeedStalledTests(unittest.TestCase):
    def test_dead_websocket_all_stale(self):
        st = {'all': [{'stale': True} for _ in range(100)]}
        self.assertTrue(_feed_stalled(st))      # WS dark -> fall back

    def test_healthy_feed_mostly_fresh(self):
        st = {'all': [{'stale': False}] * 95 + [{'stale': True}] * 5}
        self.assertFalse(_feed_stalled(st))

    def test_some_illiquid_stale_symbols_not_stalled(self):
        st = {'all': [{'stale': False}] * 80 + [{'stale': True}] * 20}
        self.assertFalse(_feed_stalled(st))     # 20% stale is normal, not a dead feed

    def test_session_closed_is_not_stalled(self):
        st = {'session_closed': True, 'all': [{'stale': True}] * 100}
        self.assertFalse(_feed_stalled(st))     # review-only, no live feed expected

    def test_empty_rows(self):
        self.assertFalse(_feed_stalled({'all': []}))
        self.assertFalse(_feed_stalled({}))


if __name__ == '__main__':
    unittest.main()
