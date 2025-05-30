from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from datetime import datetime, timedelta
from .models import User, Department, EquipmentCategory, Equipment, Booking, DepartmentAccess
from .serializers import (
    UserSerializer, DepartmentSerializer, EquipmentCategorySerializer,
    EquipmentSerializer, BookingSerializer, DepartmentAccessSerializer
)

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.contrib import messages


class DepartmentViewSet(viewsets.ReadOnlyModelViewSet):
    """API для подразделений"""
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Возвращает только доступные пользователю подразделения"""
        user = self.request.user
        if user.role == 'admin':
            return Department.objects.all()
        return user.get_accessible_departments()


class UserViewSet(viewsets.ModelViewSet):
    """API для пользователей"""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Фильтрация пользователей в зависимости от роли"""
        user = self.request.user

        if user.role == 'admin':
            return User.objects.all()
        elif user.role == 'moderator':
            # Модератор видит пользователей из своих подразделений
            accessible_deps = user.get_accessible_departments()
            return User.objects.filter(department__in=accessible_deps)
        else:
            # Обычный пользователь видит только себя
            return User.objects.filter(id=user.id)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Информация о текущем пользователе"""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class EquipmentCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """API для категорий оборудования"""
    queryset = EquipmentCategory.objects.all()
    serializer_class = EquipmentCategorySerializer
    permission_classes = [permissions.IsAuthenticated]


class EquipmentViewSet(viewsets.ReadOnlyModelViewSet):
    """API для оборудования"""
    queryset = Equipment.objects.filter(is_active=True)
    serializer_class = EquipmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Возвращает оборудование из доступных подразделений"""
        user = self.request.user
        accessible_deps = user.get_accessible_departments()
        return Equipment.objects.filter(
            is_active=True,
            department__in=accessible_deps
        )

    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        """Проверка доступности оборудования на указанную дату"""
        equipment = self.get_object()
        date_str = request.query_params.get('date')

        if not date_str:
            return Response(
                {'error': 'Параметр date обязателен (формат: YYYY-MM-DD)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Неверный формат даты. Используйте YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем бронирования на указанную дату
        bookings = Booking.objects.filter(
            equipment=equipment,
            start_time__date=date,
            status__in=['approved', 'active']
        ).order_by('start_time')

        busy_slots = []
        for booking in bookings:
            busy_slots.append({
                'start_time': booking.start_time,
                'end_time': booking.end_time,
                'user': booking.user.username
            })

        return Response({
            'date': date_str,
            'equipment': equipment.name,
            'busy_slots': busy_slots
        })


class BookingViewSet(viewsets.ModelViewSet):
    """API для бронирований"""
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Фильтрация бронирований в зависимости от роли"""
        user = self.request.user

        if user.role == 'admin':
            return Booking.objects.all()
        elif user.role == 'moderator':
            # Модератор видит бронирования из своих подразделений
            accessible_deps = user.get_accessible_departments()
            return Booking.objects.filter(equipment__department__in=accessible_deps)
        else:
            # Обычный пользователь видит только свои бронирования
            return Booking.objects.filter(user=user)

    def perform_create(self, serializer):
        """Автоматически устанавливаем текущего пользователя и отправляем уведомление"""
        from .tasks import send_booking_notification

        equipment = serializer.validated_data['equipment']

        # Определяем статус в зависимости от категории
        if equipment.category.approval_required:
            status = 'pending'
        else:
            status = 'approved'

        booking = serializer.save(user=self.request.user, status=status)

        # Отправляем уведомление асинхронно
        send_booking_notification.delay(booking.id, 'created')

    @action(detail=False, methods=['get'])
    def my_bookings(self, request):
        """Мои бронирования"""
        bookings = Booking.objects.filter(user=request.user).order_by('-created_at')
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Активные бронирования"""
        now = timezone.now()
        bookings = self.get_queryset().filter(
            status='active',
            start_time__lte=now,
            end_time__gt=now
        )
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Подтверждение бронирования (для модераторов/админов)"""
        booking = self.get_object()
        user = request.user

        if user.role not in ['admin', 'moderator']:
            return Response(
                {'error': 'У вас нет прав для подтверждения бронирований'},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.role == 'moderator' and not user.can_manage_department(booking.equipment.department):
            return Response(
                {'error': 'У вас нет прав для управления этим подразделением'},
                status=status.HTTP_403_FORBIDDEN
            )

        if booking.status != 'pending':
            return Response(
                {'error': 'Можно подтверждать только ожидающие бронирования'},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.status = 'approved'
        booking.approved_by = user
        booking.approved_at = timezone.now()
        booking.save()

        # Отправляем уведомление об одобрении
        from .tasks import send_booking_notification
        send_booking_notification.delay(booking.id, 'approved')

        serializer = self.get_serializer(booking)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Отмена бронирования"""
        booking = self.get_object()
        user = request.user

        # Проверяем права на отмену
        can_cancel = (
                booking.user == user or  # Свое бронирование
                user.role == 'admin' or  # Администратор
                (user.role == 'moderator' and user.can_manage_department(booking.equipment.department))
        )

        if not can_cancel:
            return Response(
                {'error': 'У вас нет прав для отмены этого бронирования'},
                status=status.HTTP_403_FORBIDDEN
            )

        if booking.status in ['completed', 'cancelled']:
            return Response(
                {'error': 'Нельзя отменить завершенное или уже отмененное бронирование'},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.status = 'cancelled'
        booking.save()

        serializer = self.get_serializer(booking)
        return Response(serializer.data)


class DepartmentAccessViewSet(viewsets.ModelViewSet):
    """API для управления доступами к подразделениям"""
    queryset = DepartmentAccess.objects.all()
    serializer_class = DepartmentAccessSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Только админы и модераторы могут управлять доступами"""
        user = self.request.user

        if user.role == 'admin':
            return DepartmentAccess.objects.all()
        elif user.role == 'moderator':
            # Модератор видит доступы только для своих подразделений
            accessible_deps = user.get_accessible_departments()
            return DepartmentAccess.objects.filter(department__in=accessible_deps)
        else:
            # Обычные пользователи не могут управлять доступами
            return DepartmentAccess.objects.none()

    def perform_create(self, serializer):
        """Автоматически устанавливаем, кто предоставил доступ"""
        serializer.save(granted_by=self.request.user)


@login_required
def dashboard(request):
    """Главная страница"""
    context = {
        'user': request.user,
        'accessible_departments': request.user.get_accessible_departments(),
    }
    return render(request, 'booking/dashboard.html', context)


@login_required
def equipment_list(request):
    """Список оборудования"""
    user = request.user
    accessible_departments = user.get_accessible_departments()
    equipments = Equipment.objects.filter(
        is_active=True,
        department__in=accessible_departments
    ).select_related('category', 'department')

    context = {
        'equipments': equipments,
        'departments': accessible_departments,
    }
    return render(request, 'booking/equipment_list.html', context)


@login_required
def my_bookings(request):
    """Мои бронирования"""
    bookings = Booking.objects.filter(
        user=request.user
    ).select_related('equipment', 'equipment__department').order_by('-start_time')

    context = {
        'bookings': bookings,
    }
    return render(request, 'booking/my_bookings.html', context)


@login_required
def user_management(request):
    """Управление пользователями (для админов и модераторов)"""
    if request.user.role not in ['admin', 'moderator']:
        messages.error(request, "У вас нет доступа к этой странице")
        return redirect('dashboard')

    if request.user.role == 'admin':
        users = User.objects.all()
        departments = Department.objects.all()
    else:  # moderator
        accessible_deps = request.user.get_accessible_departments()
        users = User.objects.filter(department__in=accessible_deps)
        departments = accessible_deps

    context = {
        'users': users,
        'departments': departments,
    }
    return render(request, 'booking/user_management.html', context)


@login_required
def profile(request):
    """Профиль пользователя"""
    return render(request, 'booking/profile.html')


class CustomLoginView(auth_views.LoginView):
    """Кастомная страница входа"""
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return '/dashboard/'


from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .forms import BookingForm, EquipmentFilterForm


@login_required
def create_booking(request, equipment_id=None):
    """Создание нового бронирования"""
    equipment = None
    if equipment_id:
        equipment = get_object_or_404(Equipment, id=equipment_id)
        # Проверяем права доступа
        if not request.user.can_book_in_department(equipment.department):
            messages.error(request, "У вас нет прав для бронирования в этом подразделении")
            return redirect('equipment_list')

    if request.method == 'POST':
        form = BookingForm(request.POST, user=request.user)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.user = request.user

            # Определяем статус
            if booking.equipment.category.approval_required:
                booking.status = 'pending'
                status_message = "Бронирование создано и ожидает подтверждения"
            else:
                booking.status = 'approved'
                status_message = "Бронирование успешно создано и подтверждено"

            booking.save()

            # Отправляем уведомление
            from .tasks import send_booking_notification
            send_booking_notification.delay(booking.id, 'created')

            messages.success(request, status_message)
            return redirect('my_bookings')
    else:
        initial_data = {}
        if equipment:
            initial_data['equipment'] = equipment
        form = BookingForm(user=request.user, initial=initial_data)

    context = {
        'form': form,
        'equipment': equipment,
    }
    return render(request, 'booking/create_booking.html', context)


@login_required
def cancel_booking(request, booking_id):
    """Отмена бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    # Проверяем права на отмену
    can_cancel = (
            booking.user == request.user or
            request.user.role == 'admin' or
            (request.user.role == 'moderator' and
             request.user.can_manage_department(booking.equipment.department))
    )

    if not can_cancel:
        messages.error(request, "У вас нет прав для отмены этого бронирования")
        return redirect('my_bookings')

    if booking.status in ['completed', 'cancelled']:
        messages.error(request, "Нельзя отменить завершенное или уже отмененное бронирование")
        return redirect('my_bookings')

    if request.method == 'POST':
        booking.status = 'cancelled'
        booking.save()

        # Отправляем уведомление
        from .tasks import send_booking_notification
        send_booking_notification.delay(booking.id, 'cancelled')

        messages.success(request, "Бронирование успешно отменено")
        return redirect('my_bookings')

    context = {'booking': booking}
    return render(request, 'booking/cancel_booking.html', context)


@login_required
def equipment_availability(request, equipment_id):
    """AJAX проверка доступности оборудования"""
    equipment = get_object_or_404(Equipment, id=equipment_id)
    date_str = request.GET.get('date')

    if not date_str:
        return JsonResponse({'error': 'Параметр date обязателен'}, status=400)

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Неверный формат даты'}, status=400)

    # Получаем бронирования на указанную дату
    bookings = Booking.objects.filter(
        equipment=equipment,
        start_time__date=date,
        status__in=['approved', 'active']
    ).order_by('start_time')

    busy_slots = []
    for booking in bookings:
        busy_slots.append({
            'start_time': booking.start_time.strftime('%H:%M'),
            'end_time': booking.end_time.strftime('%H:%M'),
            'user': booking.user.username if request.user.role in ['admin', 'moderator'] else 'Занято'
        })

    return JsonResponse({
        'date': date_str,
        'equipment': equipment.name,
        'busy_slots': busy_slots
    })


@login_required
def approve_booking(request, booking_id):
    """Подтверждение бронирования (для модераторов/админов)"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user.role not in ['admin', 'moderator']:
        messages.error(request, "У вас нет прав для подтверждения бронирований")
        return redirect('dashboard')

    if request.user.role == 'moderator' and not request.user.can_manage_department(booking.equipment.department):
        messages.error(request, "У вас нет прав для управления этим подразделением")
        return redirect('dashboard')

    if booking.status != 'pending':
        messages.error(request, "Можно подтверждать только ожидающие бронирования")
        return redirect('dashboard')

    if request.method == 'POST':
        booking.status = 'approved'
        booking.approved_by = request.user
        booking.approved_at = timezone.now()
        booking.save()

        # Отправляем уведомление
        from .tasks import send_booking_notification
        send_booking_notification.delay(booking.id, 'approved')

        messages.success(request, f"Бронирование пользователя {booking.user.username} подтверждено")
        return redirect('pending_bookings')

    context = {'booking': booking}
    return render(request, 'booking/approve_booking.html', context)


@login_required
def pending_bookings(request):
    """Список ожидающих подтверждения бронирований"""
    if request.user.role not in ['admin', 'moderator']:
        messages.error(request, "У вас нет доступа к этой странице")
        return redirect('dashboard')

    if request.user.role == 'admin':
        bookings = Booking.objects.filter(status='pending')
    else:  # moderator
        accessible_deps = request.user.get_accessible_departments()
        bookings = Booking.objects.filter(
            status='pending',
            equipment__department__in=accessible_deps
        )

    bookings = bookings.select_related(
        'user', 'equipment', 'equipment__department'
    ).order_by('start_time')

    context = {'bookings': bookings}
    return render(request, 'booking/pending_bookings.html', context)

