"""Write the synthetic fleet, dataset and generated Mosquitto ACL to disk."""
from .config import ACL_TEST_LOCK, write_json, write_jsonl
from .dataset import build_dataset
from .fleet import (build_fleet, render_acl, render_client_identities, render_emqx_acl, render_hivemq_client_ids,
                    render_hivemq_permissions)


def generate(cfg, out_dir, acl_path, emqx_acl_path=None, hivemq_permissions_path=None):
    if acl_path is not None and ACL_TEST_LOCK.exists():
        raise SystemExit(f'ACL test lock present ({ACL_TEST_LOCK}); finish or recover test 09/10 first.')
    fleet = build_fleet(cfg)
    data = build_dataset(cfg, fleet)
    write_json(out_dir / 'fleet.json', fleet)
    (out_dir / 'gateways.txt').write_text(''.join(g['gateway_id'] + '\n' for g in fleet['gateways']))
    (out_dir / 'services.txt').write_text(''.join(s['identity'] + '\n' for s in fleet['services']))
    (out_dir / 'legacy_gateways.txt').write_text(''.join(g['gateway_id'] + '\n'
                                                         for g in fleet.get('legacy_gateways', [])))
    (out_dir / 'client_identities.tsv').write_text(render_client_identities(fleet))
    write_jsonl(out_dir / 'dataset' / 'telemetry.jsonl', data['telemetry'])
    write_jsonl(out_dir / 'dataset' / 'commands.jsonl', data['commands'])
    write_json(out_dir / 'dataset' / 'connectivity.json', data['connectivity'])
    write_json(out_dir / 'dataset' / 'summary.json', data['summary'])
    write_acls(fleet, acl_path, emqx_acl_path, hivemq_permissions_path)
    return fleet, data['summary']


def write_acls(fleet, acl_path, emqx_acl_path=None, hivemq_permissions_path=None, withdraw=None):
    """Broker authorization files from the fleet. `withdraw`: leave out every grant of that Gateway ID."""
    if withdraw:
        fleet = dict(fleet, gateways=[g for g in fleet['gateways'] if g['gateway_id'] != withdraw],
                     legacy_gateways=[g for g in fleet.get('legacy_gateways', []) if g['gateway_id'] != withdraw])
    # Rewrite in place (open 'w'): keeps the inode of single-file Docker bind mounts.
    if acl_path is not None:
        with open(acl_path, 'w') as f:
            f.write(render_acl(fleet))
    if emqx_acl_path is not None:
        # Same rules for the EMQX broker profile (brokers/emqx/).
        emqx_acl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(emqx_acl_path, 'w') as f:
            f.write(render_emqx_acl(fleet))
    if hivemq_permissions_path is not None:
        hivemq_permissions_path.parent.mkdir(parents=True, exist_ok=True)
        with open(hivemq_permissions_path, 'w') as f:
            f.write(render_hivemq_permissions(fleet))
        with open(hivemq_permissions_path.parent / 'client_ids.tsv', 'w') as f:
            f.write(render_hivemq_client_ids(fleet))
