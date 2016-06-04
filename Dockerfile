FROM blowb/uwsgi:python2

COPY requirements.txt /var/uwsgi/
RUN pip install -r /var/uwsgi/requirements.txt
COPY bible.py /var/uwsgi/
COPY res /var/uwsgi/res
COPY tmpl /var/uwsgi/tmpl
VOLUME /var/uwsgi/db

ENV WSGI_MODULE=bible:app

