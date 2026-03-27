# Start MongoDB in the background. Data lives in Docker volume
# http-validator-mongo-data and survives stop/restart. Do not use
# `docker compose down -v` locally unless you intend to wipe the DB.
#
#   make          # start (default goal)
#   make stop     # stop containers; volume is kept
#
# Runs save to Mongo by default at mongodb://127.0.0.1:27017 (override with MONGODB_URI
# or --mongo-uri). Use --no-mongo for file-only output.

.DEFAULT_GOAL := mongo

.PHONY: mongo stop

mongo:
	docker compose up -d

stop:
	docker compose down
