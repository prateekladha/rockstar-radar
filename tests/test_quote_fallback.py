"""Offline tests for FYERS quote failures and supported POST fallback."""
import unittest
from radar.fyers import (FyersAdapter, ApiError, ApiAuthError, ApiRateLimitError,
                         ApiProviderError)


class FakeLimiter:
    def __init__(self):
        self.used = 0
    def acquire(self):
        self.used += 1


class RequestFailureClient:
    def __init__(self):
        self.calls = []
    def quotes(self, data):
        self.calls.append(('get', data))
        return {'s': 'error', 'code': -99, 'message': 'Bad request'}
    def quotes_v2(self, data):
        self.calls.append(('post', data))
        return {'s': 'ok', 'code': 200, 'd': [
            {'n': name, 's': 'ok', 'v': {'lp': 250.0, 'prev_close_price': 249}}
            for name in data['symbols']
        ]}


class MixedValidityClient:
    def __init__(self):
        self.calls = []
    def quotes(self, data):
        symbols = data['symbols'].split(',')
        self.calls.append(symbols)
        if 'NSE:BAD-EQ' in symbols:
            return {'s': 'error', 'code': -300, 'message': 'Invalid symbol'}
        return {'s': 'ok', 'code': 200, 'd': [
            {'n': s, 's': 'ok', 'v': {'lp': 350.0}}
            for s in symbols
        ]}


class AuthenticationClient:
    def __init__(self, code):
        self.code = code
        self.calls = 0
    def quotes(self, data):
        self.calls += 1
        return {'s': 'error', 'code': self.code, 'message': 'not authorized'}


class OpaqueProviderFailureClient:
    def __init__(self):
        self.calls = 0
    def quotes(self, data):
        self.calls += 1
        return {'s': 'error', 'code': -99, 'message': 'Bad request'}
    def quotes_v2(self, data):
        self.calls += 1
        return {'s': 'error', 'code': -99, 'message': 'Bad request'}


class QuoteFallbackTests(unittest.TestCase):
    def adapter(self, client):
        adapter = FyersAdapter.__new__(FyersAdapter)
        adapter.client = client
        adapter.limit = FakeLimiter()
        return adapter

    def test_succeeds_using_post_v2_if_get_fails(self):
        client = RequestFailureClient()
        adapter = self.adapter(client)
        result = adapter.quotes([f'NSE:S{i}-EQ' for i in range(50)])
        self.assertEqual(len(result), 50)
        self.assertEqual([type_ for type_, _ in client.calls], ['get', 'post'])
        self.assertIsInstance(client.calls[-1][1]['symbols'], list)
        self.assertEqual(len(client.calls[-1][1]['symbols']), 50)

    def test_isolates_invalid_symbol_and_preserves_good_quotes(self):
        client = MixedValidityClient()
        adapter = self.adapter(client)
        symbols = [f'NSE:S{i}-EQ' for i in range(39)] + ['NSE:BAD-EQ']
        result = adapter.quotes(symbols)
        self.assertEqual(len(result), 39)
        self.assertNotIn('NSE:BAD-EQ', result)
        self.assertTrue(all(len(x) <= 50 for x in client.calls))

    def test_auth_failure_not_retried_or_split(self):
        client = AuthenticationClient(-8)
        adapter = self.adapter(client)
        with self.assertRaises(ApiAuthError):
            adapter.quotes([f'NSE:S{i}-EQ' for i in range(50)])
        self.assertEqual(client.calls, 1)

    def test_rate_limit_not_retried_or_split(self):
        client = AuthenticationClient(-360)
        adapter = self.adapter(client)
        with self.assertRaises(ApiRateLimitError):
            adapter.quotes([f'NSE:S{i}-EQ' for i in range(50)])
        self.assertEqual(client.calls, 1)

    def test_generic_bad_request_is_not_retried_identically(self):
        client = RequestFailureClient()
        adapter = self.adapter(client)
        with self.assertRaises(ApiError):
            adapter.request('quotes', {'symbols': 'NSE:SBIN-EQ'})
        self.assertEqual(len(client.calls), 1)

    def test_opaque_provider_failure_stops_without_recursive_bisection(self):
        client = OpaqueProviderFailureClient()
        adapter = self.adapter(client)
        with self.assertRaises(ApiProviderError):
            adapter.quotes([f'NSE:S{i}-EQ' for i in range(50)])
        self.assertEqual(client.calls, 2, 'Must not fan out 50 failed symbols into 100 requests')

    def test_cloudflare_1015_is_rate_limit_not_input_error(self):
        client = AuthenticationClient(-99)
        def banned(data):
            client.calls += 1
            return {'s':'error','code':-99,
                    'message':'Error 1015: The owner of this website has banned you temporarily'}
        client.quotes = banned
        adapter = self.adapter(client)
        with self.assertRaises(ApiRateLimitError):
            adapter.quotes([f'NSE:S{i}-EQ' for i in range(50)])
        self.assertEqual(client.calls, 1)


if __name__ == '__main__':
    unittest.main()
