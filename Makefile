.PHONY: setup test sim demo demo-start demo-stop dashboard seed reset-data coreml

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PY) -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

test:
	$(PY) -m pytest tests/ -v

sim:
	bash scripts/run_all.sh --simulate

demo:
	bash scripts/run_all.sh

# One command to reach a demo-ready state (see docs/demo-2min.md)
demo-start:
	bash scripts/demo_start.sh

demo-stop:
	bash scripts/demo_stop.sh

dashboard:
	$(PY) -m streamlit run storesmart/dashboard/app.py

seed:
	$(PY) -m storesmart.stock.seed

reset-data:
	rm -f data/storesmart.db data/storesmart.db-wal data/storesmart.db-shm
	rm -f config/store_map.json config/shelf_slots.json

coreml:
	$(PY) -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='coreml')"
