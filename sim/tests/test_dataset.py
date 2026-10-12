import json
import os
import re
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest import mock

from enetec_sim import wire
from enetec_sim.config import LAB_ROOT, encode, load_config, parse_utc, read_jsonl
from enetec_sim.dataset import build_dataset, offline_at
from enetec_sim.fleet import build_fleet, render_acl, render_client_identities
from enetec_sim.generate import generate

PLANT_UUID7 = re.compile(r'^plt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


class CommittedDataTest(unittest.TestCase):
    """synthetic/ and mosquitto/config/acl must be exactly what sim/config.toml produces."""

    def test_committed_files_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, acl, emqx = Path(tmp) / 'synthetic', Path(tmp) / 'acl', Path(tmp) / 'emqx-acl.conf'
            generate(load_config(), out, acl, emqx)
            for rel in ('fleet.json', 'gateways.txt', 'services.txt', 'legacy_gateways.txt', 'client_identities.tsv',
                        'dataset/telemetry.jsonl',
                        'dataset/commands.jsonl', 'dataset/connectivity.json', 'dataset/summary.json'):
                with self.subTest(rel):
                    self.assertEqual((out / rel).read_bytes(), (LAB_ROOT / 'synthetic' / rel).read_bytes(),
                                     f'{rel} is stale: run make fleet and commit the result')
            self.assertEqual(acl.read_bytes(), (LAB_ROOT / 'mosquitto/config/acl').read_bytes())
            self.assertEqual(emqx.read_bytes(), (LAB_ROOT / 'brokers/emqx/acl.conf').read_bytes())


class FleetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.fleet = build_fleet(cls.cfg)

    def test_identity_rule_and_uniqueness(self):
        ids = [g['gateway_id'] for g in self.fleet['gateways']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.cfg['wire']['client_id'], 'derived')
        client_ids = set()
        for gw in self.fleet['gateways']:
            self.assertEqual(gw['certificate_cn'], gw['gateway_id'])
            # ENTC-47: Client ID = pseudonym of the gateway serial, not the serial, not the credential name.
            self.assertEqual(gw['client_id'], wire.derive_client_id(gw['serial_number']))
            self.assertRegex(gw['client_id'], r'^c[0-9a-f]{20}$')
            self.assertNotIn(gw['serial_number'], gw['client_id'])
            client_ids.add(gw['client_id'])
        self.assertEqual(len(client_ids), len(ids))
        serials = [d['serial_number'] for g in self.fleet['gateways'] for d in g['devices']]
        serials += [g['serial_number'] for g in self.fleet['gateways']]
        self.assertEqual(len(serials), len(set(serials)))
        self.assertTrue(all(0 <= int(s) < 2 ** 32 for s in serials))

    def test_lab_gateways_pinned_and_plant_ids_canonical(self):
        by_id = {g['gateway_id']: g for g in self.fleet['gateways']}
        for pin in self.cfg['fleet']['pinned']:
            self.assertEqual(by_id[pin['gateway_id']]['plant_id'], pin['plant_id'])
        pinned_plants = {p['plant_id'] for p in self.cfg['fleet']['pinned']}
        for plant in self.fleet['plants']:
            if plant['plant_id'] not in pinned_plants:
                self.assertRegex(plant['plant_id'], PLANT_UUID7)

    def test_legacy_gateways_have_no_certificate_identity(self):
        legacy = self.fleet['legacy_gateways']
        self.assertEqual([g['gateway_id'] for g in legacy], self.cfg['legacy']['gateway_ids'])
        for gw in legacy:
            self.assertRegex(gw['gateway_id'], r'^\d{16}$')
            self.assertIsNone(gw['certificate_cn'])
            self.assertEqual(gw['client_id'], wire.derive_client_id(gw['gateway_id']))
        # Legacy gateways are not part of the simulated traffic.
        self.assertFalse({g['gateway_id'] for g in legacy} & {g['gateway_id'] for g in self.fleet['gateways']})

    def test_acl_is_gateway_scoped(self):
        # v1.3: exactly the own state (write) and cmd (read) topic, keyed on the certificate identity.
        acl = render_acl(self.fleet)
        for gw in self.fleet['gateways']:
            block = acl.split(f"user {gw['gateway_id']}\n", 1)[1].split('\n\n', 1)[0].splitlines()
            self.assertEqual(block, [f"topic write enetec/v1/{gw['client_id']}/state",
                                     f"topic read  enetec/v1/{gw['client_id']}/cmd"])
        for svc in self.fleet['services']:
            self.assertEqual(bool(svc['read']) + bool(svc['write']), 1, 'service must be one-directional')
        self.assertEqual([s['read'] + s['write'] for s in self.fleet['services']],
                         [['enetec/v1/+/state'], ['enetec/v1/+/cmd']])

    def test_client_identity_registry(self):
        rows = [line.split('\t') for line in render_client_identities(self.fleet).splitlines()
                if not line.startswith('#')]
        expected = [[g['gateway_id'], g['serial_number'], g['client_id'], 'lab-sha256-v0']
                    for g in self.fleet['gateways'] + self.fleet['legacy_gateways']]
        self.assertEqual(rows, expected)

    def test_lab_eicp_profile_keeps_the_previous_layout(self):
        with mock.patch.dict(os.environ, {'SIM_WIRE': 'lab-eicp'}):
            cfg = load_config()
        fleet = build_fleet(cfg)
        acl = render_acl(fleet)
        for gw in fleet['gateways']:
            self.assertEqual(gw['client_id'], gw['gateway_id'])
            base = f"{cfg['topics']['base']}/{gw['plant_id']}/gateways/{gw['gateway_id']}"
            block = acl.split(f"user {gw['gateway_id']}\n", 1)[1].split('\n\n', 1)[0].splitlines()
            self.assertEqual(block, [f'topic write {base}/d2c/#', f'topic read  {base}/c2d/#'])
        row = build_dataset(cfg, fleet)['telemetry'][0]
        gw = next(g for g in fleet['gateways'] if g['gateway_id'] == row['gateway_id'])
        self.assertEqual(row['topic'], f"{cfg['topics']['base']}/{gw['plant_id']}/gateways/{gw['gateway_id']}"
                                       '/d2c/telemetry/report')

    def test_unknown_wire_profile_is_refused(self):
        with mock.patch.dict(os.environ, {'SIM_WIRE': 'v99'}), self.assertRaises(SystemExit):
            load_config()

    def test_envelope_matches_lab_sample(self):
        sample = json.loads((LAB_ROOT / 'samples' / 'telemetry.json').read_text())
        data = build_dataset(self.cfg, self.fleet)
        message = data['telemetry'][0]['message']
        self.assertEqual(message.keys(), sample.keys())
        self.assertEqual(message['payload'].keys(), sample['payload'].keys())
        self.assertEqual(message['payload']['measurements'].keys(), sample['payload']['measurements'].keys())


class DatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.fleet = build_fleet(cls.cfg)
        cls.data = build_dataset(cls.cfg, cls.fleet)
        cls.skew = {g['gateway_id']: g['clock_skew_s'] for g in cls.fleet['gateways']}
        cls.by_gateway = defaultdict(list)
        for row in cls.data['telemetry']:
            cls.by_gateway[row['gateway_id']].append(row)

    def test_volume_matches_planning_baseline(self):
        per_day = self.data['summary']['telemetry']['per_gateway_per_day']
        self.assertAlmostEqual(per_day, self.cfg['dataset']['d2c_per_gateway_per_day'], delta=0.05 * per_day)

    def test_message_ids_unique(self):
        ids = [r['message']['messageId'] for r in self.data['telemetry']]
        ids += [c['message']['messageId'] for c in self.data['commands']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sequence_fifo_and_no_send_while_offline(self):
        for gid, rows in self.by_gateway.items():
            windows = self.data['connectivity'][gid]
            rows = sorted(rows, key=lambda r: r['message']['sequenceNumber'])
            self.assertEqual([r['message']['sequenceNumber'] for r in rows], list(range(1, len(rows) + 1)))
            self.assertEqual([r['created_t'] for r in rows], sorted(r['created_t'] for r in rows))
            sent = [r['t'] for r in rows if not r['dropped']]
            self.assertEqual(sent, sorted(sent), f'{gid}: gateway must send FIFO')
            for t in sent:
                self.assertIsNone(offline_at(windows, t), f'{gid}: send at {t} while offline')

    def test_buffering_keeps_measurement_time_and_drops_oldest(self):
        start, total_dropped = parse_utc(self.cfg['dataset']['start']), 0
        for gid, rows in self.by_gateway.items():
            windows = self.data['connectivity'][gid]
            for row in rows:
                if row['buffered'] and not row['dropped']:
                    # Sent later than measured; measuredAt stays the original measurement time.
                    self.assertGreater(row['t'], row['created_t'])
                    self.assertGreaterEqual(row['message']['timestamp'],
                                            parse_utc(row['message']['payload']['measuredAt']))
                    self.assertEqual(parse_utc(row['message']['payload']['measuredAt']),
                                     int(start + row['created_t'] + self.skew[gid]))
                if row['dropped']:
                    total_dropped += 1
                    self.assertIsNotNone(offline_at(windows, row['created_t']))
            for i, _ in enumerate(windows):
                inside = [r for r in rows if offline_at(windows, r['created_t']) == i]
                flags = [r['dropped'] for r in inside]
                self.assertEqual(flags, sorted(flags, reverse=True), 'overflow must drop the oldest first')
                self.assertLessEqual(flags.count(False), self.cfg['connectivity']['buffer_max_messages'])
        self.assertGreater(total_dropped, 0, 'default config should exercise buffer overflow')

    def test_commands_and_incidents(self):
        summary = self.data['summary']
        self.assertGreater(summary['commands']['during_outage'], 0)
        for command in self.data['commands']:
            windows = self.data['connectivity'][command['gateway_id']]
            self.assertEqual(command['during_outage'], offline_at(windows, command['t']) is not None)
        storm = summary['connectivity']['incident_gateways']['regional-isp-outage']
        self.assertEqual(storm, round(0.5 * len(self.fleet['gateways'])))

    def test_payload_sizes_reported_against_baseline(self):
        sizes = [len(encode(r['message'])) for r in self.data['telemetry'] if not r['dropped']]
        self.assertEqual(max(sizes), self.data['summary']['telemetry']['payload_bytes_max'])
        self.assertLessEqual(max(sizes), self.cfg['baseline']['max_payload_bytes'])

    def test_committed_dataset_loads(self):
        rows = read_jsonl(LAB_ROOT / 'synthetic' / 'dataset' / 'telemetry.jsonl')
        self.assertEqual(len(rows), self.data['summary']['telemetry']['generated'])


if __name__ == '__main__':
    unittest.main()
