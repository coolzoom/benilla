.PHONY: test check gates

# The reproducible default: no WoW install, no network, and the pinned Cargo.lock.
test:
	./dev.sh offline

check:
	./dev.sh test

gates:
	./dev.sh gates
