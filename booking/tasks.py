from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Booking, User
import logging
import asyncio

logger = logging.getLogger(__name__)


@shared_task
def send_booking_notification(booking_id, notification_type):
    """Отправка уведомлений в Telegram"""
    try:
        booking = Booking.objects.get(id=booking_id)
        user = booking.user

        # Проверяем, подключен ли Telegram
        if not user.telegram_chat_id:
            logger.info(f"Пользователь {user.username} не подключил Telegram")
            return f"Telegram не подключен для пользователя {user.username}"

        # Формируем сообщение
        if notification_type == 'created':
            if booking.status == 'pending':
                message = f"📝 Бронирование создано и ожидает подтверждения!\n\n"
            else:
                message = f"✅ Бронирование создано и подтверждено!\n\n"
        elif notification_type == 'approved':
            message = f"✅ Ваше бронирование подтверждено!\n\n"
        elif notification_type == 'reminder':
            time_until = booking.start_time - timezone.now()
            hours = int(time_until.total_seconds() // 3600)
            minutes = int((time_until.total_seconds() % 3600) // 60)

            if hours > 0:
                time_str = f"через {hours} ч. {minutes} мин."
            else:
                time_str = f"через {minutes} мин."

            message = f"⏰ Напоминание о бронировании!\n\n"
            message += f"Начало {time_str}\n\n"
        elif notification_type == 'completed':
            message = f"✅ Бронирование завершено!\n\n"
        elif notification_type == 'cancelled':
            message = f"❌ Бронирование отменено!\n\n"
        else:
            message = f"📋 Обновление бронирования!\n\n"

        # Добавляем детали бронирования
        message += f"🔧 Оборудование: {booking.equipment.name}\n"
        message += f"📅 Время: {booking.start_time.strftime('%d.%m.%Y %H:%M')} - {booking.end_time.strftime('%H:%M')}\n"
        message += f"🏢 Подразделение: {booking.equipment.department.name}\n"

        if booking.equipment.location:
            message += f"📍 Местоположение: {booking.equipment.location}\n"

        message += f"📝 Цель: {booking.purpose}\n"

        if notification_type == 'reminder':
            message += f"\n💡 Не забудьте подойти вовремя!"
        elif notification_type == 'approved':
            message += f"\n💡 Можете приступать к использованию в назначенное время."

        # Отправляем уведомление через бота (СИНХРОННО)
        success = send_telegram_message_sync(user.telegram_chat_id, message)

        if success:
            logger.info(f"Уведомление отправлено пользователю {user.username}: {notification_type}")
            return f"Уведомление отправлено: {notification_type}"
        else:
            logger.error(f"Не удалось отправить уведомление пользователю {user.username}")
            return f"Ошибка отправки уведомления"

    except Booking.DoesNotExist:
        logger.error(f"Бронирование с ID {booking_id} не найдено")
        return f"Бронирование с ID {booking_id} не найдено"
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {str(e)}")
        return f"Ошибка: {str(e)}"


def send_telegram_message_sync(chat_id, message):
    """Синхронная отправка сообщения в Telegram"""
    try:
        from .telegram_bot import get_bot
        bot = get_bot()
        return bot.send_notification(chat_id, message)
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return False


@shared_task
def check_booking_reminders():
    """Проверка и отправка напоминаний о бронированиях"""
    now = timezone.now()

    # Напоминания за 2 часа
    reminder_time_2h = now + timedelta(hours=2)
    bookings_2h = Booking.objects.filter(
        status='approved',
        start_time__gte=now,
        start_time__lte=reminder_time_2h
    ).exclude(
        # Исключаем те, кому уже отправляли напоминание
        id__in=Booking.objects.filter(
            status='approved',
            start_time__gte=now - timedelta(hours=2, minutes=5),
            start_time__lte=now - timedelta(hours=1, minutes=55)
        ).values_list('id', flat=True)
    )

    # Напоминания за 15 минут (для коротких бронирований)
    reminder_time_15m = now + timedelta(minutes=15)
    bookings_15m = Booking.objects.filter(
        status='approved',
        start_time__gte=now,
        start_time__lte=reminder_time_15m,
        end_time__lte=now + timedelta(hours=2)  # только для бронирований короче 2 часов
    ).exclude(
        # Исключаем те, кому уже отправляли напоминание
        id__in=Booking.objects.filter(
            status='approved',
            start_time__gte=now - timedelta(minutes=20),
            start_time__lte=now - timedelta(minutes=10)
        ).values_list('id', flat=True)
    )

    reminders_sent = 0

    # Отправляем напоминания за 2 часа
    for booking in bookings_2h:
        send_booking_notification.delay(booking.id, 'reminder')
        reminders_sent += 1

    # Отправляем напоминания за 15 минут
    for booking in bookings_15m:
        send_booking_notification.delay(booking.id, 'reminder')
        reminders_sent += 1

    logger.info(f"Отправлено {reminders_sent} напоминаний")
    return f"Отправлено {reminders_sent} напоминаний"


@shared_task
def auto_complete_bookings():
    """Автоматическое завершение истекших бронирований"""
    now = timezone.now()

    # Находим активные бронирования, которые должны завершиться
    expired_bookings = Booking.objects.filter(
        status__in=['approved', 'active'],
        end_time__lt=now
    )

    completed_count = 0

    for booking in expired_bookings:
        booking.status = 'completed'
        booking.save()

        # Отправляем уведомление о завершении
        send_booking_notification.delay(booking.id, 'completed')
        completed_count += 1

    logger.info(f"Автоматически завершено {completed_count} бронирований")
    return f"Завершено {completed_count} бронирований"


@shared_task
def create_recurring_bookings():
    """Создание повторяющихся бронирований"""
    # TODO: Реализуем позже
    logger.info("Проверка повторяющихся бронирований")
    return "Повторяющиеся бронирования проверены"


@shared_task
def test_task():
    """Тестовая задача для проверки работы Celery"""
    logger.info("Тестовая задача выполнена успешно!")
    return "Тестовая задача выполнена!"
