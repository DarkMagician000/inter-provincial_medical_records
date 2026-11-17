.PHONY: all site-down site-up

all:
	bash scripts/cluster.sh all
	$(MAKE) up MACHINE=A
	$(MAKE) data
	$(MAKE) load
	$(MAKE) link
	$(MAKE) check
	$(MAKE) bench

site-down site-up:
	bash scripts/cluster.sh $@ "$(SITE)"
