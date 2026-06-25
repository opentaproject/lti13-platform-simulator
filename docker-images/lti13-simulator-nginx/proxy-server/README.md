## Run openta in dev mod

To run openta in dev mode and use https-proxy to serve pages as https:

- make sure that openta runs locally via localhost
-  getdefault nginx installation working locally from apt-get install
- Install letsencrypt and make sure https serves the standard nginx welcome
- copy https-proxy.conf /etc/nginx/sites-enabled and make sure the letsencrypt parts are properly referenced in https-proxy
- note that https-proxy.conf is essentially the openta.conf file except for the proxy setting
- copy https-openta-proxy-setting.conf to /etc/nginx/sites-enabled
- delete default in /etc/nginx/sites-enabled
- from django.backend run python manage.py rqworker
-  Run either of the following commands :
	-	`gunicorn backend.wsgi:application --bind 0.0.0.0:8000`
	- `python manage.py runserver 0.0.0.0:8000`


