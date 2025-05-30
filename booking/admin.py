from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Department, EquipmentCategory, Equipment, Booking, DepartmentAccess


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'created_at']
    search_fields = ['name', 'code']
    list_filter = ['created_at']


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'role', 'department', 'is_active']
    list_filter = ['role', 'department', 'is_active', 'date_joined']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {
            'fields': ('role', 'department', 'phone', 'telegram_key', 'telegram_chat_id')
        }),
    )


@admin.register(DepartmentAccess)
class DepartmentAccessAdmin(admin.ModelAdmin):
    list_display = ['user', 'department', 'can_view', 'can_book', 'can_manage', 'granted_by', 'created_at']
    list_filter = ['can_view', 'can_book', 'can_manage', 'created_at']
    search_fields = ['user__username', 'department__name', 'granted_by__username']

    fieldsets = (
        ('Основная информация', {
            'fields': ('user', 'department')
        }),
        ('Разрешения', {
            'fields': ('can_view', 'can_book', 'can_manage')
        }),
        ('Служебная информация', {
            'fields': ('granted_by',),
            'classes': ('collapse',)
        }),
    )


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'approval_required', 'max_booking_hours']
    list_filter = ['approval_required']
    search_fields = ['name']


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'inventory_number', 'category', 'department', 'is_active']
    list_filter = ['category', 'department', 'is_active']
    search_fields = ['name', 'inventory_number']
    list_editable = ['is_active']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'user', 'start_time', 'end_time', 'status', 'created_at']
    list_filter = ['status', 'equipment__category', 'created_at']
    search_fields = ['equipment__name', 'user__username', 'purpose']
    date_hierarchy = 'start_time'
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Основная информация', {
            'fields': ('user', 'equipment', 'start_time', 'end_time', 'status')
        }),
        ('Детали', {
            'fields': ('purpose', 'notes')
        }),
        ('Повторение', {
            'fields': ('is_recurring', 'recurrence_pattern', 'parent_booking'),
            'classes': ('collapse',)
        }),
        ('Подтверждение', {
            'fields': ('approved_by', 'approved_at'),
            'classes': ('collapse',)
        }),
        ('Служебная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
