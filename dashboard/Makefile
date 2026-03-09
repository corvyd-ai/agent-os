.PHONY: dev backend frontend install screenshot screenshot-all

DASHBOARD_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

dev:
	@echo "Starting agent-os Dashboard..."
	@make -j2 backend frontend

backend:
	cd $(DASHBOARD_DIR)/.. && uvicorn agent_os.dashboard.app:app --port 8787 --reload

frontend:
	cd $(DASHBOARD_DIR)/frontend && npm run dev

install:
	pip install -e "$(DASHBOARD_DIR)/..[dashboard]"
	cd $(DASHBOARD_DIR)/frontend && npm install

screenshot:
	cd $(DASHBOARD_DIR) && python screenshot.py $(ROUTE)

screenshot-all:
	cd $(DASHBOARD_DIR) && python screenshot.py --all
