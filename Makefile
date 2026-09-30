.PHONY: check init up down logs valid-publish cross-gateway wrong-clientid inspect verify clean \
	fleet negative-certs acceptance simulate sim-test

check:
	./scripts/00_check_prerequisites.sh

init:
	./scripts/03_init_lab.sh

up:
	docker compose up -d broker

down:
	docker compose down

logs:
	docker compose logs -f broker

valid-publish:
	./scripts/04_valid_publish.sh

cross-gateway:
	./scripts/05_cross_gateway_publish_should_fail.sh

wrong-clientid:
	./scripts/06_wrong_clientid_gap_test.sh

inspect:
	./scripts/07_inspect_certificate.sh

verify:
	./scripts/08_verify_chain.sh

clean:
	./scripts/09_clean.sh

# Synthetic fleet and architecture simulation (docs/mqtt-tests/synthetic-simulation.md)
fleet:
	./scripts/11_synthetic_fleet.sh

negative-certs:
	./scripts/12_create_negative_identities.sh

# ENTC-63 verification command: exit 0 only if all mandatory acceptance cases pass.
acceptance:
	./scripts/13_acceptance.sh

simulate:
	./scripts/14_simulate.sh

sim-test:
	docker compose run --rm -T --entrypoint python sim -m unittest discover -s sim/tests -t sim -v
