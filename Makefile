
.PHONY: help local-docs security_scan test clean

help:
	@echo "Usage: make [ help | local-docs | github-docs | security_scan | test | clean ]"

.mkdocs_venv/bin/activate:
	rm -rf .mkdocs_venv
	python3 -m venv .mkdocs_venv
	source .mkdocs_venv/bin/activate; pip install mkdocs

local-docs: .mkdocs_venv/bin/activate
	source .mkdocs_venv/bin/activate; mkdocs serve&
	firefox http://127.0.0.1:8000/

github-docs: .mkdocs_venv/bin/activate
	source .mkdocs_venv/bin/activate; mkdocs gh-deploy --strict

security_scan:
	security_scan/security_scan.sh

test:
	pytest -x -v tests

ansible-lint:
	source setup.sh; pip install ansible ansible-lint; ansible-lint --nocolor source/resources/playbooks

clean:
	git clean -d -f -x
	# -d: Recurse into directories
