"""Write the synthetic fleet, dataset and generated Mosquitto ACL to disk."""
from .config import ACL_TEST_LOCK, write_json, write_jsonl
from .dataset import build_dataset
from .fleet import build_fleet, render_acl, render_emqx_acl


def generate(cfg, out_dir, acl_path, emqx_acl_path=None):
    if acl_path is not None and ACL_TEST_LOCK.exists():
        raise SystemExit(f'ACL test lock present ({ACL_TEST_LOCK}); finish or recover test 09/10 first.')
    fleet = build_fleet(cfg)
    data = build_dataset(cfg, fleet)
    write_json(out_dir / 'fleet.json', fleet)
    (out_dir / 'gateways.txt').write_text(''.join(g['gateway_id'] + '\n' for g in fleet['gateways']))
    (out_dir / 'services.txt').write_text(''.join(s['identity'] + '\n' for s in fleet['services']))
    (out_dir / 'legacy_gateways.txt').write_text(''.join(g['gateway_id'] + '\n'
                                                         for g in fleet.get('legacy_gateways', [])))
    write_jsonl(out_dir / 'dataset' / 'telemetry.jsonl', data['telemetry'])
    write_jsonl(out_dir / 'dataset' / 'commands.jsonl', data['commands'])
    write_json(out_dir / 'dataset' / 'connectivity.json', data['connectivity'])
    write_json(out_dir / 'dataset' / 'summary.json', data['summary'])
    if acl_path is not None:
        # Rewrite in place: keeps the inode of a single-file Docker bind mount.
        with open(acl_path, 'w') as f:
            f.write(render_acl(fleet))
    if emqx_acl_path is not None:
        # Same rules for the EMQX broker profile (brokers/emqx/).
        emqx_acl_path.parent.mkdir(parents=True, exist_ok=True)
        emqx_acl_path.write_text(render_emqx_acl(fleet))
    return fleet, data['summary']
