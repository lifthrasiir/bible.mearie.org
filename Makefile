TAG=lifthrasiir/bible.mearie.org
PORT=48003

.PHONY: all
all: db/bible.db

db/bible.db: $(wildcard data/verses*.tar.bz2)
	python populate.py $@

.PHONY: docker
docker:
	docker build --rm --tag=${TAG} .

.PHONY: run
run: db/bible.db docker
	docker run -d -p ${PORT}:9000 -v /home/yurume/sites/bible.mearie.org/db:/var/uwsgi/db ${TAG}

.PHONY: kill
kill:
	ID=$$(docker ps -f ancestor=${TAG} -q); [ -z "$$ID" ] || docker stop $$ID

