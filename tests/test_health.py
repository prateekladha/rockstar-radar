"""Scanner-health helpers — the generic-start-failure guard that stops the quota-burning restart loop."""
import unittest
from datetime import datetime, timedelta, timezone

from radar.health import generic_failure_active


def _h(at, ok=False, need_login=False, rate_limited=False, reason='boom'):
    return {'ok': ok, 'need_login': need_login, 'rate_limited': rate_limited,
            'reason': reason, 'at': at.isoformat()}


class GenericFailureActiveTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)

    def test_none_health_is_not_a_failure(self):
        self.assertFalse(generic_failure_active(None, None, self.now))

    def test_healthy_scanner_is_not_a_failure(self):
        h = _h(self.now - timedelta(seconds=10), ok=True)
        self.assertFalse(generic_failure_active(h, None, self.now))

    def test_auth_failure_is_left_to_its_own_guard(self):
        h = _h(self.now - timedelta(seconds=10), need_login=True)
        self.assertFalse(generic_failure_active(h, None, self.now))

    def test_rate_limit_failure_is_left_to_its_own_guard(self):
        h = _h(self.now - timedelta(seconds=10), rate_limited=True)
        self.assertFalse(generic_failure_active(h, None, self.now))

    def test_recent_generic_failure_is_active(self):
        h = _h(self.now - timedelta(seconds=30))   # e.g. "too few RVOL baselines"
        self.assertTrue(generic_failure_active(h, None, self.now))

    def test_stale_generic_failure_allows_a_retry(self):
        h = _h(self.now - timedelta(seconds=700))   # older than the 600s window
        self.assertFalse(generic_failure_active(h, None, self.now))

    def test_login_after_failure_clears_it(self):
        fail_at = self.now - timedelta(seconds=30)
        token_after = self.now - timedelta(seconds=5)   # minted AFTER the crash
        self.assertFalse(generic_failure_active(_h(fail_at), token_after, self.now))

    def test_login_before_failure_does_not_clear_it(self):
        fail_at = self.now - timedelta(seconds=30)
        token_before = self.now - timedelta(seconds=90)  # minted BEFORE the crash
        self.assertTrue(generic_failure_active(_h(fail_at), token_before, self.now))

    def test_naive_timestamps_are_read_as_utc(self):
        naive_now = self.now.replace(tzinfo=None)
        naive_tok = (self.now - timedelta(seconds=90)).replace(tzinfo=None)
        self.assertTrue(generic_failure_active(_h(self.now - timedelta(seconds=30)),
                                               naive_tok, naive_now))


if __name__ == '__main__':
    unittest.main()
