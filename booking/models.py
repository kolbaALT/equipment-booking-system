from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
import uuid
from datetime import datetime, timedelta
from django.utils import timezone

class Department(models.Model):
    """Факультеты и подразделения"""
    name = models.CharField(max_length=100, verbose_name="Название")
    code = models.CharField(max_length=20, unique=True, verbose_name="Код")
    description = models.TextField(blank=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Расширенная модель пользователя"""
    ROLE_CHOICES = [
        ('admin', 'Администратор'),
        ('moderator', 'Модератор'),
        ('user', 'Пользователь'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='user',
        verbose_name="Роль"
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Основное подразделение"
    )
    telegram_key = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        verbose_name="Ключ для Telegram"
    )
    telegram_chat_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Telegram Chat ID"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Телефон"
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def save(self, *args, **kwargs):
        # Генерируем уникальный ключ для Telegram при создании
        if not self.telegram_key:
            self.telegram_key = str(uuid.uuid4()).replace('-', '')[:16]
        super().save(*args, **kwargs)

    def get_accessible_departments(self):
        """Возвращает подразделения, к которым у пользователя есть доступ"""
        if self.role == 'admin':
            return Department.objects.all()

        return Department.objects.filter(
            departmentaccess__user=self,
            departmentaccess__can_view=True
        ).distinct()

    def can_book_in_department(self, department):
        """Проверяет, может ли пользователь бронировать в подразделении"""
        if self.role == 'admin':
            return True

        try:
            access = DepartmentAccess.objects.get(user=self, department=department)
            return access.can_book
        except DepartmentAccess.DoesNotExist:
            return False

    def can_manage_department(self, department):
        """Проверяет, может ли пользователь управлять подразделением"""
        if self.role == 'admin':
            return True

        if self.role == 'moderator':
            try:
                access = DepartmentAccess.objects.get(user=self, department=department)
                return access.can_manage
            except DepartmentAccess.DoesNotExist:
                return False

        return False

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class DepartmentAccess(models.Model):
    """Доступ пользователей к подразделениям"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Пользователь"
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        verbose_name="Подразделение"
    )
    can_view = models.BooleanField(
        default=True,
        verbose_name="Может просматривать"
    )
    can_book = models.BooleanField(
        default=True,
        verbose_name="Может бронировать"
    )
    can_manage = models.BooleanField(
        default=False,
        verbose_name="Может управлять (для модераторов)"
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='granted_accesses',
        verbose_name="Предоставил доступ"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'department']
        verbose_name = "Доступ к подразделению"
        verbose_name_plural = "Доступы к подразделениям"
        ordering = ['user__username', 'department__name']

    def __str__(self):
        return f"{self.user.username} → {self.department.name}"


class EquipmentCategory(models.Model):
    """Категории оборудования"""
    name = models.CharField(max_length=100, verbose_name="Название")
    description = models.TextField(blank=True, verbose_name="Описание")
    approval_required = models.BooleanField(
        default=False,
        verbose_name="Требуется подтверждение"
    )
    max_booking_hours = models.PositiveIntegerField(
        default=24,
        verbose_name="Максимальное время бронирования (часы)"
    )

    class Meta:
        verbose_name = "Категория оборудования"
        verbose_name_plural = "Категории оборудования"
        ordering = ['name']

    def __str__(self):
        return self.name


class Equipment(models.Model):
    """Оборудование"""
    name = models.CharField(max_length=200, verbose_name="Название")
    description = models.TextField(blank=True, verbose_name="Описание")
    category = models.ForeignKey(
        EquipmentCategory,
        on_delete=models.CASCADE,
        verbose_name="Категория"
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        verbose_name="Подразделение"
    )
    inventory_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Инвентарный номер"
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Местоположение"
    )
    is_active = models.BooleanField(default=True, verbose_name="Активно")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Оборудование"
        verbose_name_plural = "Оборудование"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.inventory_number})"

    def is_available(self, start_time, end_time, exclude_booking=None):
        """Проверка доступности оборудования в указанное время"""
        bookings = self.booking_set.filter(
            start_time__lt=end_time,
            end_time__gt=start_time,
            status__in=['approved', 'active']
        )
        if exclude_booking:
            bookings = bookings.exclude(id=exclude_booking.id)
        return not bookings.exists()


class Booking(models.Model):
    """Бронирования"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('approved', 'Подтверждено'),
        ('active', 'Активно'),
        ('completed', 'Завершено'),
        ('cancelled', 'Отменено'),
        ('rejected', 'Отклонено'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Пользователь"
    )
    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.CASCADE,
        verbose_name="Оборудование"
    )
    start_time = models.DateTimeField(verbose_name="Время начала")
    end_time = models.DateTimeField(verbose_name="Время окончания")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Статус"
    )
    purpose = models.TextField(verbose_name="Цель использования")
    notes = models.TextField(blank=True, verbose_name="Примечания")

    # Поля для повторяющихся бронирований
    is_recurring = models.BooleanField(default=False, verbose_name="Повторяющееся")
    recurrence_pattern = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Шаблон повторения"
    )
    parent_booking = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Родительское бронирование"
    )

    # Служебные поля
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_bookings',
        verbose_name="Подтвердил"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Бронирование"
        verbose_name_plural = "Бронирования"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.equipment.name} - {self.user.username} ({self.start_time.strftime('%d.%m.%Y %H:%M')})"

    def clean(self):
        """Валидация модели"""
        from django.core.exceptions import ValidationError

        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError("Время начала должно быть раньше времени окончания")

            if self.start_time < timezone.now():
                raise ValidationError("Нельзя бронировать на прошедшее время")

    @property
    def duration(self):
        """Продолжительность бронирования"""
        return self.end_time - self.start_time

    @property
    def can_be_extended(self):
        """Можно ли продлить бронирование"""
        return self.status == 'active' and self.end_time > datetime.now()
