.PHONY: dev backend frontend install screenshot screenshot-all

DASHBOARD_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(shell git rev-parse --show-toplevel)

dev:
	@echo "Starting agent-os Dashboard..."
	@make -j2 backend frontend

backend:
	cd $(REPO_ROOT) && uvicorn agent_os.dashboard.app:app --port 8787 --reload

frontend:
	cd $(DASHBOARD_DIR)/frontend && npm run dev

install:
	pip install -e "$(REPO_ROOT)[dashboard]"
	cd $(DASHBOARD_DIR)/frontend && npm install

screenshot:
	cd $(DASHBOARD_DIR) && python screenshot.py $(ROUTE)

screenshot-all:
	cd $(DASHBOARD_DIR) && python screenshot.py --all
