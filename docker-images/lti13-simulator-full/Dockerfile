FROM opentaproject/lti13-simulator-base:multi
ARG DJANGO_SECRET_KEY
WORKDIR /srv
COPY ./srv /srv
WORKDIR /srv/lti13-simulator
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN apt install -y at 
RUN apt update 
WORKDIR /srv/lti13-simulator
#RUN python manage.py collectstatic --noinput --clear
EXPOSE 8000
