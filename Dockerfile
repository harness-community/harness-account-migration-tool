FROM python

ADD requirements.txt /app/requirements.txt
WORKDIR /app

RUN pip install -r requirements.txt
ADD . /app

ENTRYPOINT ["python", "harness_migration.py"]
