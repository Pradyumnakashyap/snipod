IMAGE_NAME ?= snipod
TAG ?= latest

export PYTHONPATH := $(PWD)/app

build:
	docker build -t $(IMAGE_NAME):$(TAG) .

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

test:
	pytest tests/

format:
	isort app tests
	black app tests

.PHONY: build run test format
