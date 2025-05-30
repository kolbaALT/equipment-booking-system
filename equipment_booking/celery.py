import os
from celery import Celery

# Устанавливаем переменную окружения для Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'equipment_booking.settings')

app = Celery('equipment_booking')

# Загружаем настройки из Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически находим задачи в приложениях
app.autodiscover_tasks()
