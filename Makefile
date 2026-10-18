PYTHON ?= /usr/bin/python3

.PHONY: run test gui-test check translations translations-check deb source release

run:
	PYTHONPATH=src $(PYTHON) -B -m malferma_libro

test:
	PYTHONPATH=src $(PYTHON) -B -m unittest discover -s tests -v

gui-test:
	PYTHONPATH=src $(PYTHON) -B packaging/check_gui.py

translations:
	$(PYTHON) -B packaging/translations.py --compile

translations-check:
	$(PYTHON) -B packaging/translations.py --check

check: test translations-check

deb:
	$(PYTHON) -B packaging/build.py deb

source:
	$(PYTHON) -B packaging/build.py source

release:
	$(PYTHON) -B packaging/build.py all
