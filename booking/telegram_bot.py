import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import Booking, DepartmentAccess
from asgiref.sync import sync_to_async

User = get_user_model()
logger = logging.getLogger(__name__)


class EquipmentBookingBot:
    def __init__(self):
        self.application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("mybookings", self.my_bookings_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_booking_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start - регистрация пользователя"""
        chat_id = update.effective_chat.id

        # Проверяем, есть ли уже привязанный пользователь
        user = await sync_to_async(self.get_user_by_chat_id)(chat_id)

        if user:
            await update.message.reply_text(
                f"👋 Привет, {user.username}!\n\n"
                f"Ваш аккаунт уже привязан к боту.\n\n"
                f"Доступные команды:\n"
                f"/mybookings - мои бронирования\n"
                f"/help - справка"
            )
            return

        await update.message.reply_text(
            "🤖 Добро пожаловать в систему бронирования оборудования!\n\n"
            "Для привязки аккаунта отправьте ваш персональный ключ.\n\n"
            "Ключ можно найти в профиле на сайте.\n\n"
            "Пример: abc123def456"
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений (ключи привязки)"""
        chat_id = update.effective_chat.id
        message_text = update.message.text.strip()

        # Проверяем, не привязан ли уже аккаунт
        user = await sync_to_async(self.get_user_by_chat_id)(chat_id)
        if user:
            await update.message.reply_text(
                "Ваш аккаунт уже привязан! Используйте /help для списка команд."
            )
            return

        # Пытаемся найти пользователя по ключу
        user = await sync_to_async(self.get_user_by_telegram_key)(message_text)

        if user:
            # Привязываем аккаунт
            user.telegram_chat_id = chat_id
            await sync_to_async(user.save)()

            await update.message.reply_text(
                f"✅ Аккаунт успешно привязан!\n\n"
                f"Добро пожаловать, {user.username}!\n"
                f"Роль: {user.get_role_display()}\n\n"
                f"Теперь вы будете получать уведомления о бронированиях.\n\n"
                f"Доступные команды:\n"
                f"/mybookings - мои бронирования\n"
                f"/help - справка"
            )
        else:
            await update.message.reply_text(
                "❌ Неверный ключ привязки.\n\n"
                "Проверьте ключ в вашем профиле на сайте и попробуйте снова."
            )

    async def my_bookings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /mybookings - список бронирований пользователя"""
        chat_id = update.effective_chat.id
        user = await sync_to_async(self.get_user_by_chat_id)(chat_id)

        if not user:
            await update.message.reply_text(
                "❌ Аккаунт не привязан. Используйте /start для привязки."
            )
            return

        bookings = await sync_to_async(self.get_user_bookings_with_equipment)(user)

        if not bookings:
            await update.message.reply_text("📅 У вас нет активных бронирований.")
            return

        message = "📅 Ваши бронирования:\n\n"
        keyboard = []

        for booking in bookings:
            status_emoji = {
                'pending': '⏳',
                'approved': '✅',
                'active': '🔄',
                'completed': '✅',
                'cancelled': '❌'
            }.get(booking.status, '❓')

            message += (
                f"{status_emoji} {booking.equipment.name}\n"
                f"📅 {booking.start_time.strftime('%d.%m.%Y %H:%M')} - "
                f"{booking.end_time.strftime('%H:%M')}\n"
                f"🏢 {booking.equipment.department.name}\n"
                f"📊 {booking.get_status_display()}\n\n"
            )

            # Добавляем кнопку отмены для активных бронирований
            if booking.status in ['pending', 'approved']:
                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ Отменить #{booking.id}",
                        callback_data=f"cancel_{booking.id}"
                    )
                ])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message, reply_markup=reply_markup)

    async def cancel_booking_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /cancel [id] - отмена бронирования"""
        chat_id = update.effective_chat.id
        user = await sync_to_async(self.get_user_by_chat_id)(chat_id)

        if not user:
            await update.message.reply_text(
                "❌ Аккаунт не привязан. Используйте /start для привязки."
            )
            return

        # Получаем ID бронирования из аргументов
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите ID бронирования.\n\nПример: /cancel 123"
            )
            return

        try:
            booking_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Неверный ID бронирования.")
            return

        booking = await sync_to_async(self.get_booking_by_id_with_equipment)(booking_id, user)


        if not booking:
            await update.message.reply_text("❌ Бронирование не найдено.")
            return

        if booking.status not in ['pending', 'approved']:
            await update.message.reply_text(
                "❌ Нельзя отменить это бронирование (статус: {booking.get_status_display()})."
            )
            return

        # Отменяем бронирование
        booking.status = 'cancelled'
        await sync_to_async(booking.save)()

        await update.message.reply_text(
            f"✅ Бронирование #{booking.id} отменено.\n\n"
            f"🔧 {booking.equipment.name}\n"
            f"📅 {booking.start_time.strftime('%d.%m.%Y %H:%M')}"
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()

        if query.data.startswith('cancel_'):
            booking_id = int(query.data.split('_')[1])
            chat_id = query.from_user.id
            user = await sync_to_async(self.get_user_by_chat_id)(chat_id)

            if not user:
                await query.edit_message_text("❌ Ошибка: аккаунт не привязан.")
                return

            booking = await sync_to_async(self.get_booking_by_id_with_equipment)(booking_id, user)

            if booking and booking.status in ['pending', 'approved']:
                booking.status = 'cancelled'
                await sync_to_async(booking.save)()

                await query.edit_message_text(
                    f"✅ Бронирование #{booking.id} отменено.\n\n"
                    f"🔧 {booking.equipment.name}\n"
                    f"📅 {booking.start_time.strftime('%d.%m.%Y %H:%M')}"
                )
            else:
                await query.edit_message_text("❌ Не удалось отменить бронирование.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help - справка"""
        help_text = (
            "🤖 Бот системы бронирования оборудования\n\n"
            "📋 Доступные команды:\n\n"
            "/start - привязка аккаунта\n"
            "/mybookings - мои бронирования\n"
            "/cancel [ID] - отменить бронирование\n"
            "/help - эта справка\n\n"
            "💡 Для привязки аккаунта отправьте ваш персональный ключ из профиля на сайте.\n\n"
            "📧 Вы будете получать уведомления о:\n"
            "• Создании бронирования\n"
            "• Подтверждении модератором\n"
            "• Напоминаниях перед началом\n"
            "• Завершении бронирования"
        )

        await update.message.reply_text(help_text)

    # Синхронные методы для работы с базой данных
    def get_user_by_chat_id(self, chat_id):
        try:
            return User.objects.get(telegram_chat_id=chat_id)
        except User.DoesNotExist:
            return None

    def get_user_by_telegram_key(self, key):
        try:
            return User.objects.get(telegram_key=key)
        except User.DoesNotExist:
            return None

    def get_user_bookings(self, user):
        return list(Booking.objects.filter(
            user=user,
            status__in=['pending', 'approved', 'active']
        ).select_related('equipment', 'equipment__department').order_by('start_time')[:10])

    def get_booking_by_id(self, booking_id, user):
        try:
            return Booking.objects.get(id=booking_id, user=user)
        except Booking.DoesNotExist:
            return None

    def send_notification(self, chat_id, message):
        """Отправка уведомления"""
        print(f"🔍 Отправляем сообщение в чат {chat_id}")
        print(f"📝 Текст: {message[:100]}...")

        result = self.send_message(chat_id, message)
        print(f"✅ Результат отправки: {result}")

        return result

    def run_polling(self):
        """Запуск бота в режиме polling"""
        print("🤖 Telegram бот запущен...")
        self.application.run_polling()

    def get_booking_by_id_with_equipment(self, booking_id, user):
        try:
            return Booking.objects.select_related('equipment').get(id=booking_id, user=user)
        except Booking.DoesNotExist:
            return None

    def get_user_bookings_with_equipment(self, user):
        return list(Booking.objects.filter(
            user=user,
            status__in=['pending', 'approved', 'active']
        ).select_related('equipment', 'equipment__department').order_by('start_time')[:10])




# Глобальный экземпляр бота
bot_instance = None


def get_bot():
    """Получение экземпляра бота"""
    global bot_instance
    if bot_instance is None:
        bot_instance = EquipmentBookingBot()
    return bot_instance
