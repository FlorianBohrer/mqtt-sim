.PHONY: check init up down logs valid-publish cross-gateway wrong-clientid inspect verify clean \
	fleet negative-certs legacy-certs acceptance simulate sim-test brokers bevywise-config bevywise-bundle compare \
	decide version

# Broker under test for acceptance/simulate: profile sim/targets/$(BROKER).toml
# e.g. make acceptance BROKER=emqx   (list: make brokers)
BROKER ?= mosquitto-lab
SIM_TARGET ?= sim/targets/$(BROKER).toml
export SIM_TARGET

# Wire profile: empty = sim/config.toml [wire] (v13: enetec/v1/{clientId}/state|cmd, derived Client ID);
# WIRE=lab-eicp = earlier layout eicp/v1/sim/.../d2c|c2d with Client ID = CN (also needed by tests 04-10)
WIRE ?=
ifneq ($(WIRE),)
export SIM_WIRE := $(WIRE)
endif

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
	./scripts/sim_run.sh scripts/12_create_negative_identities.sh

legacy-certs:
	./scripts/sim_run.sh scripts/15_create_legacy_identities.sh

# ENTC-63 verification command: exit 0 only if all mandatory acceptance cases pass.
acceptance:
	./scripts/13_acceptance.sh

simulate:
	./scripts/14_simulate.sh

# Bevywise: ACL request bodies from the fleet (brokers/bevywise/README.md)
bevywise-config:
	@if [ "$${SIM_LOCAL:-0}" = 1 ]; then PYTHONPATH=sim python3 -m enetec_sim bevywise-acl; \
	else docker build -q -t enetec-sim:local sim >/dev/null && docker compose run --rm -T sim bevywise-acl; fi

# Bevywise installation bundle (certificates, conf values, ACL): make bevywise-bundle [BEVYWISE_HOST=name]
bevywise-bundle: bevywise-config
	@BEVYWISE_HOST="$(BEVYWISE_HOST)" ./brokers/bevywise/make_bundle.sh

# Version of this lab package (also in the file VERSION)
version:
	@cat VERSION

# Compare two brokers: make compare A=hivemq B=mosquitto-lab [FRESH=1]
compare:
	@A="$(A)" B="$(B)" FRESH="$(FRESH)" ./scripts/16_compare.sh

brokers:
	@ls sim/targets/*.toml | sed 's#sim/targets/##; s#\.toml##'

# Weighted decision matrix over the latest acceptance runs (sim/decision.toml): make decide
decide:
	@./scripts/18_decide.sh

sim-test:
	docker build -q -t enetec-sim:local sim >/dev/null
	docker compose run --rm -T --entrypoint python sim -m unittest discover -s sim/tests -t sim -v
