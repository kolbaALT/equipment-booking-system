from rest_framework import serializers
from .models import User, Department, EquipmentCategory, Equipment, Booking, DepartmentAccess


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'code', 'description', 'created_at']


class DepartmentAccessSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    granted_by_name = serializers.CharField(source='granted_by.username', read_only=True)

    class Meta:
        model = DepartmentAccess
        fields = [
            'id', 'user', 'user_name', 'department', 'department_name',
            'can_view', 'can_book', 'can_manage', 'granted_by',
            'granted_by_name', 'created_at'
        ]


class UserSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    accessible_departments = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'role_display', 'department', 'department_name',
            'phone', 'telegram_key', 'is_active', 'date_joined',
            'accessible_departments'
        ]
        extra_kwargs = {
            'telegram_key': {'read_only': True},
            'password': {'write_only': True}
        }

    def get_accessible_departments(self, obj):
        """Возвращает список доступных подразделений"""
        departments = obj.get_accessible_departments()
        return DepartmentSerializer(departments, many=True).data


class EquipmentCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentCategory
        fields = [
            'id', 'name', 'description', 'approval_required', 'max_booking_hours'
        ]


class EquipmentSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    is_available_now = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            'id', 'name', 'description', 'category', 'category_name',
            'department', 'department_name', 'inventory_number',
            'location', 'is_active', 'is_available_now', 'created_at', 'updated_at'
        ]

    def get_is_available_now(self, obj):
        """Проверяет доступность оборудования прямо сейчас"""
        from datetime import datetime, timedelta
        now = datetime.now()
        return obj.is_available(now, now + timedelta(hours=1))


class BookingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)
    equipment_department = serializers.CharField(source='equipment.department.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration_hours = serializers.SerializerMethodField()
    can_be_extended = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = [
            'id', 'user', 'user_name', 'equipment', 'equipment_name', 'equipment_department',
            'start_time', 'end_time', 'status', 'status_display',
            'purpose', 'notes', 'duration_hours', 'can_be_extended',
            'is_recurring', 'created_at', 'updated_at'
        ]

    def get_duration_hours(self, obj):
        """Возвращает продолжительность в часах"""
        duration = obj.duration
        return round(duration.total_seconds() / 3600, 2)

    def validate(self, data):
        """Валидация данных бронирования"""
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        equipment = data.get('equipment')
        user = self.context['request'].user

        if start_time and end_time:
            if start_time >= end_time:
                raise serializers.ValidationError(
                    "Время начала должно быть раньше времени окончания"
                )

            # Проверка доступности оборудования
            if equipment and not equipment.is_available(start_time, end_time):
                raise serializers.ValidationError(
                    "Оборудование уже забронировано на это время"
                )

            # Проверка прав доступа к подразделению
            if equipment and not user.can_book_in_department(equipment.department):
                raise serializers.ValidationError(
                    "У вас нет прав для бронирования в этом подразделении"
                )

        return data
