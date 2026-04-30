REPORTS_DIR ?= reports

.PHONY: test lint format test-vmaas

test:
	mkdir -p $(REPORTS_DIR)
	pytest tests/ -v $(if $(TEST),-k "$(TEST)") --junitxml=$(REPORTS_DIR)/results.xml

lint:
	ruff check tests/
	ruff format --check tests/

format:
	ruff format tests/

test-vmaas:
	mkdir -p $(REPORTS_DIR)
	pytest tests/vmaas/ -v $(if $(TEST),-k "$(TEST)") --junitxml=$(REPORTS_DIR)/vmaas.xml
