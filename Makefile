.PHONY: test compile check

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests

compile:
	PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q src tests

check: test compile
