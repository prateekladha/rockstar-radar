"""Configurable universe (any index / cap)."""
import unittest

from radar import universe as U


class UniverseTests(unittest.TestCase):
    def test_catalog_has_caps(self):
        cat = U.catalog()
        ids = {c['id'] for c in cat}
        self.assertIn('nifty50', ids)
        self.assertIn('niftymidcap150', ids)
        self.assertIn('niftysmallcap250', ids)
        self.assertTrue(all(c['cap'] for c in cat))

    def test_url_for_known_and_default(self):
        self.assertTrue(U.url_for('nifty50').endswith('ind_nifty50list.csv'))
        self.assertTrue(U.url_for('niftymidcap150').endswith('ind_niftymidcap150list.csv'))
        # unknown falls back to the default index
        self.assertEqual(U.url_for('garbage'), U.url_for(U.DEFAULT))

    def test_is_valid(self):
        self.assertTrue(U.is_valid('nifty500'))
        self.assertFalse(U.is_valid('nope'))

    def test_label_for(self):
        self.assertEqual(U.label_for('niftysmallcap250'), 'Nifty Smallcap 250')


if __name__ == '__main__':
    unittest.main()
