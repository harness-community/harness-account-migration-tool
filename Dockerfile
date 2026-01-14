FROM python
ADD requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt
ADD . /app
WORKDIR /app

