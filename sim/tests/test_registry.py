"""Lab registry for the EMQX HTTP authenticator (brokers/registry/registry.py): decision rules."""
import importlib.util
import json
import unittest

from enetec_sim.config import LAB_ROOT

spec = importlib.util.spec_from_file_location('registry', LAB_ROOT / 'brokers' / 'registry' / 'registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class RegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fleet = json.loads((LAB_ROOT / 'synthetic' / 'fleet.json').read_text())
        cls.allowed = registry.authorised_ids(cls.fleet)
        cls.gw = cls.fleet['gateways'][0]

    def decide(self, cn, client_id, connected=lambda cid: False, **kw):
        return registry.decide(self.allowed, cn, client_id, connected, **kw)

    def test_every_fleet_identity_has_its_client_id(self):
        for gw in self.fleet['gateways']:
            self.assertEqual(self.allowed[gw['certificate_cn']], gw['client_id'])
        for svc in self.fleet['services']:
            self.assertEqual(self.allowed[svc['identity']], svc['client_id'])

    def test_authorised_client_id_is_allowed(self):
        self.assertEqual(self.decide(self.gw['certificate_cn'], self.gw['client_id'])[0], 'allow')

    def test_foreign_or_plain_cn_client_id_is_denied(self):
        other = self.fleet['gateways'][1]
        self.assertEqual(self.decide(self.gw['certificate_cn'], other['client_id'])[0], 'deny')   # ID-01
        self.assertEqual(self.decide(self.gw['certificate_cn'], self.gw['certificate_cn'])[0], 'deny')   # ID-03

    def test_unknown_or_missing_cn_is_denied(self):
        self.assertEqual(self.decide('gw-sim-900001', 'c0000')[0], 'deny')   # ACL-13: not in the fleet
        self.assertEqual(self.decide('', '0000000000000005')[0], 'deny')    # legacy certificate without CN

    def test_live_duplicate_is_denied_after_the_grace_period(self):
        now = [0.0]
        result = self.decide(self.gw['certificate_cn'], self.gw['client_id'], lambda cid: True, grace_s=3,
                             sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        self.assertEqual(result[0], 'deny')
        self.assertGreaterEqual(now[0], 3)

    def test_old_connection_that_disappears_within_the_grace_period_is_allowed(self):
        answers = iter([True, True, False])   # a dropped link the broker notices after two polls
        self.assertEqual(self.decide(self.gw['certificate_cn'], self.gw['client_id'], lambda cid: next(answers),
                                     sleep=lambda s: None)[0], 'allow')

    def test_broker_error_propagates_so_the_server_fails_closed(self):
        def broken(cid):
            raise OSError('API not reachable')
        with self.assertRaises(OSError):
            self.decide(self.gw['certificate_cn'], self.gw['client_id'], broken)
