from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.contrib.auth import views as auth_views
from . import views

# Создаем роутер для API
router = DefaultRouter()
router.register(r'departments', views.DepartmentViewSet)
router.register(r'users', views.UserViewSet)
router.register(r'equipment-categories', views.EquipmentCategoryViewSet)
router.register(r'equipment', views.EquipmentViewSet)
router.register(r'bookings', views.BookingViewSet)
router.register(r'department-access', views.DepartmentAccessViewSet)

urlpatterns = [
    # Фронтенд маршруты
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('equipment/', views.equipment_list, name='equipment_list'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('users/', views.user_management, name='user_management'),
    path('profile/', views.profile, name='profile'),

    # Бронирования
    path('booking/create/', views.create_booking, name='create_booking'),
    path('booking/create/<int:equipment_id>/', views.create_booking, name='create_booking_for_equipment'),
    path('booking/<int:booking_id>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('booking/<int:booking_id>/approve/', views.approve_booking, name='approve_booking'),
    path('pending-bookings/', views.pending_bookings, name='pending_bookings'),

    # AJAX эндпоинты
    path('equipment/<int:equipment_id>/availability/', views.equipment_availability, name='equipment_availability'),

    # Аутентификация
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # API маршруты
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),
]
