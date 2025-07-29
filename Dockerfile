# Dockerfile
FROM ubuntu:24.04
COPY requirements.txt /app/requirements.txt
WORKDIR /app

ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt update && apt -y install gunicorn && apt -y install git && apt -y install python3-pip && apt -y install poppler-utils

RUN pip install -r requirements.txt

COPY . /app
RUN chmod +x /app/build_runner/entrypoint.sh
ENTRYPOINT ["/app/build_runner/entrypoint.sh"]