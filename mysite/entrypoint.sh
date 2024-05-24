python manage.py migrate --no-input
python manage.py collectstatic --no-input

uvicorn --host 0.0.0.0 --port 8000 mysite.asgi:application
