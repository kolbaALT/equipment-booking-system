from django import forms
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from django.utils import timezone
from .models import Booking, Equipment, Department



class BookingForm(forms.ModelForm):
    """Форма создания бронирования"""

    class Meta:
        model = Booking
        fields = ['equipment', 'start_time', 'end_time', 'purpose', 'notes']
        widgets = {
            'start_time': forms.DateTimeInput(
                attrs={
                    'type': 'datetime-local',
                    'class': 'form-control',
                    'min': datetime.now().strftime('%Y-%m-%dT%H:%M')
                }
            ),
            'end_time': forms.DateTimeInput(
                attrs={
                    'type': 'datetime-local',
                    'class': 'form-control'
                }
            ),
            'purpose': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Опишите цель использования оборудования'
                }
            ),
            'notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 2,
                    'placeholder': 'Дополнительные примечания (необязательно)'
                }
            ),
            'equipment': forms.Select(
                attrs={'class': 'form-select'}
            )
        }
        labels = {
            'equipment': 'Оборудование',
            'start_time': 'Время начала',
            'end_time': 'Время окончания',
            'purpose': 'Цель использования',
            'notes': 'Примечания'
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            # Показываем только доступное оборудование
            accessible_departments = user.get_accessible_departments()
            self.fields['equipment'].queryset = Equipment.objects.filter(
                is_active=True,
                department__in=accessible_departments
            ).select_related('category', 'department')

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        equipment = cleaned_data.get('equipment')

        if start_time and end_time:
            # Проверка времени
            if start_time >= end_time:
                raise ValidationError("Время начала должно быть раньше времени окончания")

            if start_time < timezone.now():
                raise ValidationError("Нельзя бронировать на прошедшее время")

            # Проверка минимального времени бронирования (30 минут)
            if (end_time - start_time) < timedelta(minutes=30):
                raise ValidationError("Минимальное время бронирования - 30 минут")

            # Проверка максимального времени бронирования
            if equipment and equipment.category.max_booking_hours:
                max_duration = timedelta(hours=equipment.category.max_booking_hours)
                if (end_time - start_time) > max_duration:
                    raise ValidationError(
                        f"Максимальное время бронирования для этой категории - "
                        f"{equipment.category.max_booking_hours} часов"
                    )

            # Проверка доступности оборудования
            if equipment and not equipment.is_available(start_time, end_time):
                raise ValidationError("Оборудование уже забронировано на это время")

        return cleaned_data


class EquipmentFilterForm(forms.Form):
    """Форма фильтрации оборудования"""

    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        empty_label="Все подразделения",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    search = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Поиск по названию или инвентарному номеру'
            }
        )
    )

    available_only = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            # Показываем только доступные подразделения
            self.fields['department'].queryset = user.get_accessible_departments()
