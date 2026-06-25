FROM python:3.11.9-bullseye
RUN apt-get update
RUN apt-get install --yes --no-install-recommends ca-certificates curl gpg
RUN mkdir -p /data
RUN apt upgrade -y
RUN apt update -y \
    && apt-get --fix-broken install -y \
    memcached  \
    libmemcached-dev  \
    vim \
    rsync \
    apt-utils \
    redis \
    libnss3 \
    uuid \
    bc ;
RUN apt-get install --yes --no-install-recommends ca-certificates curl gpg 
RUN apt-get update -y  \
    && apt-get install -y \
    cron\
    at ; 
RUN mkdir -p /srv/lti13-simulator
COPY requirements-lti13-simulator.txt /srv/lti13-simulator/requirements.txt
WORKDIR /srv/lti13-simulator
RUN pip install --upgrade pip
RUN pip install -q  supervisor gunicorn 
RUN pip install -r requirements.txt

RUN apt-get update -y 
RUN apt-get update && apt-get install -y netcat-openbsd;
