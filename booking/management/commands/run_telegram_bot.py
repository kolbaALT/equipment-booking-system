from django.core.management.base import BaseCommand
from booking.telegram_bot import get_bot


class Command(BaseCommand):
    help = 'Запуск Telegram бота'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Запуск Telegram бота...')
        )

        bot = get_bot()
        try:
            bot.run_polling()
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.SUCCESS('Бот остановлен.')
            )
