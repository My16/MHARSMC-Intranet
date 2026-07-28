import json
import datetime

from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from .models import UserProfile, Role, DEPARTMENT_CHOICES, EmployeeCornerPost, PostAttachment, Application
from .forms import UserForm, UserEditForm, UserProfileForm
from collections import defaultdict

from django.http import JsonResponse
from .models import Notification

@login_required
def notifications_list(request):
    notifs = (
        Notification.objects
        .filter(recipient=request.user)
        .select_related('actor')[:20]
    )
    data = [
        {
            'id':         n.pk,
            'notif_type': n.notif_type,
            'title':      n.title,
            'message':    n.message,
            'url':        n.url,
            'is_read':    n.is_read,
            'actor':      n.actor.get_full_name() if n.actor else 'System',
            'created_at': timezone.localtime(n.created_at).strftime('%b %d, %Y %I:%M %p'),
        }
        for n in notifs
    ]
    return JsonResponse({'notifications': data})


def _send_group_system_message(conv, text):
    """
    Creates a system Message and broadcasts it via WebSocket.
    Call after any group membership change.
    """
    from .models import Message, Conversation
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    msg = Message.objects.create(
        conversation=conv,
        sender=None,          # system message — no sender
        body=text,
        is_system=True,
    )
    conv.updated_at = msg.created_at
    conv.save()

    msg_data = {
        'id':              msg.pk,
        'body':            msg.body,
        'sender_id':       None,
        'created_at':      msg.created_at.isoformat(),
        'attachment_url':  None,
        'attachment_name': None,
        'is_image':        False,
        'is_system':       True,
        'status':          'sent',
        'reply_to':        None,
    }

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'chat_{conv.pk}',
        {'type': 'chat_message', 'message': msg_data}
    )
    return msg


@login_required
def notifications_mark_all_read(request):
    if request.method == 'POST':
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)

# ── Module registry ────────────────────────────────────────────────────────────
MODULE_CHOICES = [
    ('press_releases',   'Press Releases'),
    ('events_trainings', 'Events & Trainings'),
    ('issuances',        'Issuances'),
    ('pgs',              'Performance Governance System'),
    ('wiki',             'Wiki'),
    ('e_library', 'e-Library'),
    ('applications',     'Applications'),
    ('directory',        'Directory'),
    ('downloads',        'Downloads'),
    ('settings',         'Settings'),
    ('user_management',  'User Management'),
    ('role_management',  'Role Management'),
]
MODULE_KEYS = [k for k, _ in MODULE_CHOICES]


# ── Auth helpers ───────────────────────────────────────────────────────────────
def is_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return hasattr(user, 'profile') and user.profile.is_administrator


def login(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            messages.error(request, 'Please enter both username and password.')
            return render(request, 'loginpage.html')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_active:
                auth_login(request, user)
                return redirect(request.GET.get('next', 'home'))
            messages.error(request, 'Your account has been disabled.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'loginpage.html')


# ── Helpers ────────────────────────────────────────────────────────────────────
def _roles_as_json():
    """
    Serialise all roles to JSON for the JS role-change handler.
    { role_id: [1,0,1,...] }  in MODULE_KEYS order.
    """
    result = {}
    for role in Role.objects.all():
        result[str(role.pk)] = [1 if role.has_access(k) else 0 for k in MODULE_KEYS]
    return json.dumps(result)


# ── User Management ────────────────────────────────────────────────────────────
@login_required
@user_passes_test(is_admin)
def user_management(request):
    search_query = request.GET.get('search', '').strip()

    profiles_qs = UserProfile.objects.select_related(
        'user', 'role'
    ).filter(
        user__is_superuser=False
    ).order_by('user__date_joined')

    if search_query:
        profiles_qs = profiles_qs.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query)  |
            Q(user__username__icontains=search_query)   |
            Q(user__email__icontains=search_query)
        )

    base_qs        = UserProfile.objects.filter(user__is_superuser=False)
    total_users    = base_qs.count()
    active_users   = base_qs.filter(user__is_active=True).count()
    inactive_users = base_qs.filter(user__is_active=False).count()
    pending_users = base_qs.filter(user__is_active=False, access_reason__gt='').count()

    roles = Role.objects.all().order_by('name')

    return render(request, 'user_management.html', {
        'profiles':         profiles_qs,
        'total_users':      total_users,
        'active_users':     active_users,
        'inactive_users':   inactive_users,
        'pending_users':    pending_users,
        'search_query':     search_query,
        'module_choices':   MODULE_CHOICES,
        'roles':            roles,
        'roles_json':       _roles_as_json(),
        'department_choices': DEPARTMENT_CHOICES,
    })


@login_required
@user_passes_test(is_admin)
def user_add(request):
    if request.method == 'POST':
        password         = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not password:
            messages.error(request, 'Password is required.')
            return redirect('user_management')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('user_management')

        form_user    = UserForm(request.POST)
        form_profile = UserProfileForm(request.POST, request.FILES)

        if form_user.is_valid() and form_profile.is_valid():
            user = form_user.save(commit=False)
            user.set_password(password)
            user.is_active = True
            user.save()

            profile      = form_profile.save(commit=False)
            profile.user = user

            role_pk = request.POST.get('role')
            if role_pk:
                try:
                    profile.role = Role.objects.get(pk=role_pk)
                except Role.DoesNotExist:
                    profile.role = None

            profile.save()

            messages.success(request, f'User "{profile.get_full_name_with_middle()}" has been created.')
            return redirect('user_management')
        else:
            for field, errs in {**form_user.errors, **form_profile.errors}.items():
                for err in errs:
                    messages.error(request, f'{field}: {err}')
            return redirect('user_management')

    return redirect('user_management')

def register(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        first_name       = request.POST.get('first_name', '').strip()
        middle_name      = request.POST.get('middle_name', '').strip()
        last_name        = request.POST.get('last_name', '').strip()
        email            = request.POST.get('email', '').strip()
        mobile_number    = request.POST.get('mobile_number', '').strip()
        department       = request.POST.get('department', '').strip()
        position         = request.POST.get('position', '').strip()
        reason           = request.POST.get('reason', '').strip()
        username         = request.POST.get('username', '').strip()
        password         = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = []

        if not all([first_name, last_name, email, department, position, reason, username, password]):
            errors.append('Please fill in all required fields.')

        if password != confirm_password:
            errors.append('Passwords do not match.')

        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')

        if User.objects.filter(username__iexact=username).exists():
            errors.append(f'Username "{username}" is already taken.')

        if User.objects.filter(email__iexact=email).exists():
            errors.append('An account with that email already exists.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'register.html')

        # Create user as inactive — IT admin activates it
        user = User.objects.create_user(
            username   = username,
            email      = email,
            password   = password,
            first_name = first_name,
            last_name  = last_name,
            is_active  = False,   # pending IT approval
        )

        # Create the profile
        UserProfile.objects.create(
            user          = user,
            middle_name   = middle_name,
            department    = department,
            position      = position,
            mobile_number = mobile_number,
            access_reason = reason,
        )

        messages.success(request, 'Your access request has been submitted. The IT Team will activate your account within 1–2 business days.')
        return redirect('login')

    return render(request, 'register.html', {'department_choices': DEPARTMENT_CHOICES,})


@login_required
@user_passes_test(is_admin)
def user_edit(request, pk):
    profile = get_object_or_404(UserProfile, user__pk=pk, user__is_superuser=False)
    user    = profile.user

    if request.method == 'POST':
        new_password     = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if new_password and new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('user_management')

        form_user    = UserEditForm(request.POST, instance=user)
        form_profile = UserProfileForm(request.POST, request.FILES, instance=profile)

        if form_user.is_valid() and form_profile.is_valid():
            user_obj = form_user.save(commit=False)

            if new_password:
                user_obj.set_password(new_password)

            user_obj.is_active = 'is_active' in request.POST
            user_obj.save()

            profile_obj = form_profile.save(commit=False)

            role_pk = request.POST.get('role')
            if role_pk:
                try:
                    profile_obj.role = Role.objects.get(pk=role_pk)
                except Role.DoesNotExist:
                    profile_obj.role = None
            else:
                profile_obj.role = None

            profile_obj.save()

            messages.success(request, f'User "{profile.get_full_name_with_middle()}" has been updated.')
        else:
            for field, errs in {**form_user.errors, **form_profile.errors}.items():
                for err in errs:
                    messages.error(request, f'{field}: {err}')

    return redirect('user_management')


@login_required
@user_passes_test(is_admin)
def user_toggle(request, pk):
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    target = get_object_or_404(User, pk=pk, is_superuser=False)

    if target == request.user:
        return JsonResponse({'success': False, 'error': 'You cannot deactivate your own account.'})

    target.is_active = not target.is_active
    target.save()

    name   = target.profile.get_full_name_with_middle() if hasattr(target, 'profile') else target.username
    status = 'activated' if target.is_active else 'deactivated'

    return JsonResponse({
        'success':   True,
        'is_active': target.is_active,
        'message':   f'"{name}" has been {status}.',
    })


@login_required
@user_passes_test(is_admin)
def user_delete(request, pk):
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk, is_superuser=False)
        if target != request.user:
            name = target.profile.get_full_name_with_middle() if hasattr(target, 'profile') else target.username
            target.delete()
            messages.success(request, f'User "{name}" has been deleted.')
        else:
            messages.error(request, 'You cannot delete your own account.')
    return redirect('user_management')


# ── Role Management ────────────────────────────────────────────────────────────
@login_required
@user_passes_test(is_admin)
def role_management(request):
    roles = Role.objects.all().order_by('name')

    total_roles = roles.count()
    total_assigned = UserProfile.objects.filter(
        user__is_superuser=False, role__isnull=False
    ).count()
    total_unassigned = UserProfile.objects.filter(
        user__is_superuser=False, role__isnull=True
    ).count()

    # Annotate user_count on each role for display
    roles_with_counts = []
    for role in roles:
        roles_with_counts.append({
            'role':       role,
            'user_count': role.user_count,
            'perms_list': ','.join(
                getattr(role, k, 'none') if not role.is_administrator else 'edit'
                for k in MODULE_KEYS
            ),
        })

    return render(request, 'role_management.html', {
        'roles':            roles_with_counts,
        'total_roles':      total_roles,
        'total_assigned':   total_assigned,
        'total_unassigned': total_unassigned,
        'module_choices':   MODULE_CHOICES,
        'module_keys':      MODULE_KEYS,
    })


@login_required
@user_passes_test(is_admin)
def role_add(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Role name is required.')
            return redirect('role_management')

        if Role.objects.filter(name__iexact=name).exists():
            messages.error(request, f'A role named "{name}" already exists.')
            return redirect('role_management')

        from .models import PERM_NONE, PERM_EDIT
        role = Role(name=name, description=description)

        if name.strip().lower() == 'administrator':
            for key in MODULE_KEYS:
                setattr(role, key, PERM_EDIT)
        else:
            for key in MODULE_KEYS:
                val = request.POST.get(f'perm_{key}', PERM_NONE)
                if val not in ('none', 'view', 'edit'):
                    val = PERM_NONE
                setattr(role, key, val)

        role.save()
        messages.success(request, f'Role "{name}" has been created.')
    return redirect('role_management')


@login_required
@user_passes_test(is_admin)
def role_edit(request, pk):
    role = get_object_or_404(Role, pk=pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Role name is required.')
            return redirect('role_management')

        if Role.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            messages.error(request, f'A role named "{name}" already exists.')
            return redirect('role_management')

        from .models import PERM_NONE, PERM_EDIT
        role.name = name
        role.description = description

        if name.strip().lower() == 'administrator':
            for key in MODULE_KEYS:
                setattr(role, key, PERM_EDIT)
        else:
            for key in MODULE_KEYS:
                val = request.POST.get(f'perm_{key}', PERM_NONE)
                if val not in ('none', 'view', 'edit'):
                    val = PERM_NONE
                setattr(role, key, val)

        role.save()
        messages.success(request, f'Role "{name}" has been updated.')
    return redirect('role_management')


@login_required
@user_passes_test(is_admin)
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)

    if request.method == 'POST':
        fallback_pk = request.POST.get('fallback_role')
        fallback    = None

        if fallback_pk:
            try:
                fallback = Role.objects.get(pk=fallback_pk)
            except Role.DoesNotExist:
                pass

        # Reassign all users on this role to fallback (or null)
        UserProfile.objects.filter(role=role).update(role=fallback)

        name = role.name
        role.delete()
        messages.success(request, f'Role "{name}" has been deleted.')

    return redirect('role_management')

@login_required
@user_passes_test(is_admin)
def user_approve(request, pk):
    """Approve a pending self-registration: activate the account and assign a role."""
    if request.method == 'POST':
        profile = get_object_or_404(UserProfile, user__pk=pk, user__is_superuser=False)
        user = profile.user

        user.is_active = True
        user.save()

        role_pk = request.POST.get('role')
        if role_pk:
            try:
                profile.role = Role.objects.get(pk=role_pk)
                profile.save()
            except Role.DoesNotExist:
                pass

        messages.success(request, f'"{profile.get_full_name_with_middle()}" has been approved and activated.')
    return redirect('user_management')


# ── Misc ───────────────────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('login')


# ── Home / Dashboard ──────────────────────────────────────────────────────────
@login_required
def home(request):
    from .models import (
        PressRelease, UserProfile,
    )
    from django.utils import timezone
    import datetime
 
    today = timezone.now().date()
    user  = request.user
 
    def can_access(module):
        if user.is_superuser: return True
        return hasattr(user, 'profile') and user.profile.has_module_access(module)
 
    ctx = {}
 
    # ── Press releases ──────────────────────────────────────────
    if can_access('press_releases'):
        ctx['recent_press_releases'] = (
            PressRelease.objects
            .filter(status='published')
            .select_related('author')
            .order_by('-created_at')[:5]
        )
        ctx['press_release_count'] = PressRelease.objects.filter(status='published').count()
 
    # ── Events & trainings ──────────────────────────────────────
    if can_access('events_trainings'):
        from .models import Event, Training
        ctx['upcoming_events'] = (
            Event.objects
            .filter(status='published', start_date__gte=today)
            .order_by('start_date')[:4]
        )
        ctx['upcoming_trainings'] = (
            Training.objects
            .filter(status='published', start_date__gte=today)
            .order_by('start_date')[:3]
        )
        ctx['event_count'] = Event.objects.filter(
            status='published', start_date__gte=today
        ).count()
 
    # ── Issuances ───────────────────────────────────────────────
    if can_access('issuances'):
        from .models import Issuance
        ctx['recent_issuances'] = (
            Issuance.objects
            .filter(status='published')
            .select_related('category')
            .order_by('-issuance_date')[:4]
        )
        ctx['issuance_count'] = Issuance.objects.filter(status='published').count()
 
    # ── Wiki ────────────────────────────────────────────────────
    if can_access('wiki'):
        from .models import WikiArticle
        ctx['wiki_count'] = WikiArticle.objects.filter(status='published').count()
 
    # ── Staff count & online ────────────────────────────────────
    if can_access('directory'):
        ctx['staff_count'] = UserProfile.objects.filter(
            user__is_superuser=False, user__is_active=True
        ).count()
 
    ctx['online_staff'] = UserProfile.objects.filter(
        is_online=True,
        user__is_superuser=False,
        user__is_active=True,
    ).exclude(user=user).select_related('user')[:6]
 
    return render(request, 'home.html', ctx)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _can_manage_press_releases(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('press_releases')


# ── Press Releases ─────────────────────────────────────────────────────────────
@login_required
def press_releases(request):
    from .models import PressRelease

    can_manage = _can_manage_press_releases(request.user)

    search_query  = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    month_filter  = request.GET.get('month', '')

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in (5, 10, 20, 40, 100):
        per_page = 10

    qs = PressRelease.objects.select_related('author').order_by('-created_at')

    if not can_manage:
        qs = qs.filter(status='published')
        status_filter = ''

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(details__icontains=search_query)
        )

    if can_manage and status_filter in ('draft', 'published', 'archived'):
        qs = qs.filter(status=status_filter)

    month_filter_label = ''
    if month_filter:
        try:
            year, month = month_filter.split('-')
            qs = qs.filter(created_at__year=int(year), created_at__month=int(month))
            month_filter_label = datetime.date(int(year), int(month), 1).strftime('%B %Y')
        except (ValueError, AttributeError):
            month_filter = ''

    all_dates = PressRelease.objects.dates('created_at', 'month', order='DESC')
    available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in all_dates
    ]

    if can_manage:
        total_count     = PressRelease.objects.count()
        published_count = PressRelease.objects.filter(status='published').count()
        draft_count     = PressRelease.objects.filter(status='draft').count()
        archived_count  = PressRelease.objects.filter(status='archived').count()
    else:
        total_count     = PressRelease.objects.filter(status='published').count()
        published_count = total_count
        draft_count     = None
        archived_count  = None

    paginator   = Paginator(qs, per_page)
    page_number = request.GET.get('page', '').strip() or 1
    page_obj    = paginator.get_page(page_number)

    can_view = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('press_releases')
    )

    return render(request, 'press_releases.html', {
        'press_releases':     page_obj,
        'search_query':       search_query,
        'status_filter':      status_filter,
        'month_filter':       month_filter,
        'month_filter_label': month_filter_label,
        'available_months':   available_months,
        'per_page':           per_page,
        'total_count':        total_count,
        'published_count':    published_count,
        'draft_count':        draft_count,
        'archived_count':     archived_count,
        'can_manage':         can_manage,
        'can_view':           can_view,
    })


@login_required
def press_release_create(request):
    from .models import PressRelease
    if not _can_manage_press_releases(request.user):
        messages.error(request, 'You do not have permission to create press releases.')
        return redirect('press_releases')

    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        details        = request.POST.get('details', '').strip()
        status         = request.POST.get('status', 'draft')
        archive_policy = request.POST.get('archive_policy', 'default')
        archive_date   = request.POST.get('archive_date', '') or None
        image          = request.FILES.get('image')

        if not title:
            messages.error(request, 'Title is required.')
            return redirect('press_releases')

        if status not in ('draft', 'published'):
            status = 'draft'

        pr = PressRelease(
            title          = title,
            details        = details,
            status         = status,
            archive_policy = archive_policy,
            archive_date   = archive_date,
            author         = request.user,
        )
        if image:
            pr.image = image

        pr.save()
        messages.success(request, f'Press release "{title}" has been {"published" if status == "published" else "saved as draft"}.')
        return redirect('press_releases')

    return redirect('press_releases')


@login_required
def press_release_edit(request, pk):
    from .models import PressRelease
    pr = get_object_or_404(PressRelease, pk=pk)

    if not _can_manage_press_releases(request.user):
        messages.error(request, 'You do not have permission to edit press releases.')
        return redirect('press_releases')

    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        details        = request.POST.get('details', '').strip()
        status         = request.POST.get('status', pr.status)
        archive_policy = request.POST.get('archive_policy', pr.archive_policy)
        archive_date   = request.POST.get('archive_date', '') or None
        image          = request.FILES.get('image')
        clear_image    = request.POST.get('clear_image') == '1'

        if not title:
            messages.error(request, 'Title is required.')
            return redirect('press_releases')

        if status not in ('draft', 'published', 'archived'):
            status = pr.status

        pr.title          = title
        pr.details        = details
        pr.status         = status
        pr.archive_policy = archive_policy
        pr.archive_date   = archive_date

        if clear_image and pr.image:
            pr.image.delete(save=False)
            pr.image = None
        elif image:
            if pr.image:
                pr.image.delete(save=False)
            pr.image = image

        pr.save()
        messages.success(request, f'Press release "{title}" has been updated.')
        return redirect('press_releases')

    return redirect('press_releases')


@login_required
def press_release_delete(request, pk):
    from .models import PressRelease
    pr = get_object_or_404(PressRelease, pk=pk)

    if not _can_manage_press_releases(request.user):
        messages.error(request, 'You do not have permission to delete press releases.')
        return redirect('press_releases')

    if request.method == 'POST':
        title = pr.title
        if pr.image:
            pr.image.delete(save=False)
        pr.delete()
        messages.success(request, f'Press release "{title}" has been deleted.')

    return redirect('press_releases')


@login_required
def press_release_toggle_status(request, pk):
    """AJAX: toggle between draft ↔ published, or archive/unarchive."""
    from .models import PressRelease
    if not _can_manage_press_releases(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    pr     = get_object_or_404(PressRelease, pk=pk)
    action = request.POST.get('action', '')

    if action == 'publish':
        pr.status = PressRelease.STATUS_PUBLISHED
    elif action == 'draft':
        pr.status = PressRelease.STATUS_DRAFT
    elif action == 'archive':
        pr.status = PressRelease.STATUS_ARCHIVED
    elif action == 'unarchive':
        pr.status = PressRelease.STATUS_PUBLISHED if pr.published_at else PressRelease.STATUS_DRAFT
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    pr.save()
    return JsonResponse({
        'success': True,
        'status':  pr.status,
        'label':   pr.get_status_display(),
    })


@login_required
def press_release_detail(request, pk):
    from .models import PressRelease
    pr = get_object_or_404(PressRelease, pk=pk)
    can_manage = _can_manage_press_releases(request.user)
    return render(request, 'press_release_detail.html', {
        'pr':         pr,
        'can_manage': can_manage,
    })


# ── Permission helper ──────────────────────────────────────────────────────────

def _can_manage_events(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('events_trainings')


# ── List view ──────────────────────────────────────────────────────────────────

@login_required
def events_trainings(request):
    from .models import Event, Training

    can_manage = _can_manage_events(request.user)
    active_tab = request.GET.get('tab', 'ev')

    # ── EVENTS ────────────────────────────────────────────────
    ev_search  = request.GET.get('ev_search', '').strip()
    ev_status  = request.GET.get('ev_status', '')
    ev_month   = request.GET.get('ev_month', '')

    try:
        ev_per_page = int(request.GET.get('ev_per_page', 10))
    except (ValueError, TypeError):
        ev_per_page = 10
    if ev_per_page not in (5, 10, 20, 40, 100):
        ev_per_page = 10

    ev_qs = (Event.objects.select_related('author')
             .prefetch_related('attachments')
             .order_by('-start_date', '-created_at'))

    if not can_manage:
        ev_qs = ev_qs.filter(status='published')
        ev_status = ''

    if ev_search:
        ev_qs = ev_qs.filter(
            Q(title__icontains=ev_search) | Q(details__icontains=ev_search) |
            Q(location__icontains=ev_search) | Q(summary__icontains=ev_search))

    if can_manage and ev_status in ('draft', 'published', 'archived'):
        ev_qs = ev_qs.filter(status=ev_status)

    ev_month_label = ''
    if ev_month:
        try:
            y, m = ev_month.split('-')
            ev_qs = ev_qs.filter(start_date__year=int(y), start_date__month=int(m))
            ev_month_label = datetime.date(int(y), int(m), 1).strftime('%B %Y')
        except (ValueError, AttributeError):
            ev_month = ''

    ev_available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in Event.objects.dates('start_date', 'month', order='DESC')
    ]

    ev_paginator   = Paginator(ev_qs, ev_per_page)
    ev_page_number = request.GET.get('page_ev', '').strip() or 1
    ev_page_obj    = ev_paginator.get_page(ev_page_number)

    if can_manage:
        ev_total_count     = Event.objects.count()
        ev_published_count = Event.objects.filter(status='published').count()
        ev_draft_count     = Event.objects.filter(status='draft').count()
        ev_archived_count  = Event.objects.filter(status='archived').count()
    else:
        ev_total_count     = Event.objects.filter(status='published').count()
        ev_published_count = ev_total_count
        ev_draft_count     = None
        ev_archived_count  = None

    # ── TRAININGS ──────────────────────────────────────────────
    tr_search = request.GET.get('tr_search', '').strip()
    tr_status = request.GET.get('tr_status', '')
    tr_month  = request.GET.get('tr_month', '')

    try:
        tr_per_page = int(request.GET.get('tr_per_page', 10))
    except (ValueError, TypeError):
        tr_per_page = 10
    if tr_per_page not in (5, 10, 20, 40, 100):
        tr_per_page = 10

    tr_qs = (Training.objects.select_related('author')
             .prefetch_related('attachments')
             .order_by('-start_date', '-created_at'))

    if not can_manage:
        tr_qs = tr_qs.filter(status='published')
        tr_status = ''

    if tr_search:
        tr_qs = tr_qs.filter(
            Q(title__icontains=tr_search) | Q(details__icontains=tr_search) |
            Q(location__icontains=tr_search) | Q(summary__icontains=tr_search) |
            Q(organizer__icontains=tr_search) | Q(target_participants__icontains=tr_search))

    if can_manage and tr_status in ('draft', 'published', 'archived'):
        tr_qs = tr_qs.filter(status=tr_status)

    tr_month_label = ''
    if tr_month:
        try:
            y, m = tr_month.split('-')
            tr_qs = tr_qs.filter(start_date__year=int(y), start_date__month=int(m))
            tr_month_label = datetime.date(int(y), int(m), 1).strftime('%B %Y')
        except (ValueError, AttributeError):
            tr_month = ''

    tr_available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in Training.objects.dates('start_date', 'month', order='DESC')
    ]

    tr_paginator   = Paginator(tr_qs, tr_per_page)
    tr_page_number = request.GET.get('page_tr', '').strip() or 1
    tr_page_obj    = tr_paginator.get_page(tr_page_number)

    if can_manage:
        tr_total_count     = Training.objects.count()
        tr_published_count = Training.objects.filter(status='published').count()
        tr_draft_count     = Training.objects.filter(status='draft').count()
        tr_archived_count  = Training.objects.filter(status='archived').count()
    else:
        tr_total_count     = Training.objects.filter(status='published').count()
        tr_published_count = tr_total_count
        tr_draft_count     = None
        tr_archived_count  = None

    can_view = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('events_trainings')
    )

    return render(request, 'events_trainings.html', {
        'active_tab':            active_tab,
        'can_manage':            can_manage,
        'events':                ev_page_obj,
        'ev_search_query':       ev_search,
        'ev_status_filter':      ev_status,
        'ev_month_filter':       ev_month,
        'ev_month_filter_label': ev_month_label,
        'ev_available_months':   ev_available_months,
        'ev_per_page':           ev_per_page,
        'ev_total_count':        ev_total_count,
        'ev_published_count':    ev_published_count,
        'ev_draft_count':        ev_draft_count,
        'ev_archived_count':     ev_archived_count,
        'trainings':             tr_page_obj,
        'tr_search_query':       tr_search,
        'tr_status_filter':      tr_status,
        'tr_month_filter':       tr_month,
        'tr_month_filter_label': tr_month_label,
        'tr_available_months':   tr_available_months,
        'tr_per_page':           tr_per_page,
        'tr_total_count':        tr_total_count,
        'tr_published_count':    tr_published_count,
        'tr_draft_count':        tr_draft_count,
        'tr_archived_count':     tr_archived_count,
        'can_view':              can_view,
    })

# ── Create ─────────────────────────────────────────────────────────────────────

@login_required
def event_create(request):
    from .models import Event, EventAttachment

    if not _can_manage_events(request.user):
        messages.error(request, 'You do not have permission to create events.')
        return redirect('events_trainings')

    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        location       = request.POST.get('location', '').strip()
        summary        = request.POST.get('summary', '').strip()
        details        = request.POST.get('details', '').strip()
        status         = request.POST.get('status', 'draft')
        start_date     = request.POST.get('start_date', '') or None
        end_date       = request.POST.get('end_date', '')   or None
        start_time     = request.POST.get('start_time', '') or None
        end_time       = request.POST.get('end_time', '')   or None
        archive_policy = request.POST.get('archive_policy', 'default')
        archive_date   = request.POST.get('archive_date', '') or None

        # Basic validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if not location:
            errors.append('Location is required.')
        if not details:
            errors.append('Details are required.')
        if not start_date:
            errors.append('Start date is required.')
        if status not in ('draft', 'published'):
            status = 'draft'

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('events_trainings')

        event = Event(
            title          = title,
            location       = location,
            summary        = summary,
            details        = details,
            status         = status,
            start_date     = start_date,
            end_date       = end_date,
            start_time     = start_time,
            end_time       = end_time,
            archive_policy = archive_policy,
            archive_date   = archive_date,
            author         = request.user,
        )
        event.save()

        # Handle multiple file attachments
        for f in request.FILES.getlist('attachments'):
            EventAttachment.objects.create(
                event         = event,
                file          = f,
                original_name = f.name,
            )

        verb = 'published' if status == 'published' else 'saved as draft'
        messages.success(request, f'Event "{title}" has been {verb}.')

    return redirect('events_trainings')


# ── Edit ───────────────────────────────────────────────────────────────────────

@login_required
def event_edit(request, pk):
    from .models import Event, EventAttachment

    event = get_object_or_404(Event, pk=pk)

    if not _can_manage_events(request.user):
        messages.error(request, 'You do not have permission to edit events.')
        return redirect('events_trainings')

    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        location       = request.POST.get('location', '').strip()
        summary        = request.POST.get('summary', '').strip()
        details        = request.POST.get('details', '').strip()
        status         = request.POST.get('status', event.status)
        start_date     = request.POST.get('start_date', '') or None
        end_date       = request.POST.get('end_date', '')   or None
        start_time     = request.POST.get('start_time', '') or None
        end_time       = request.POST.get('end_time', '')   or None
        archive_policy = request.POST.get('archive_policy', event.archive_policy)
        archive_date   = request.POST.get('archive_date', '') or None

        errors = []
        if not title:
            errors.append('Title is required.')
        if not location:
            errors.append('Location is required.')
        if not details:
            errors.append('Details are required.')
        if not start_date:
            errors.append('Start date is required.')
        if status not in ('draft', 'published', 'archived'):
            status = event.status

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('events_trainings')

        event.title          = title
        event.location       = location
        event.summary        = summary
        event.details        = details
        event.status         = status
        event.start_date     = start_date
        event.end_date       = end_date
        event.start_time     = start_time
        event.end_time       = end_time
        event.archive_policy = archive_policy
        event.archive_date   = archive_date
        event.save()

        # Append any new attachments (existing ones are kept unless deleted separately)
        new_files = request.FILES.getlist('attachments')
        for f in new_files:
            EventAttachment.objects.create(
                event         = event,
                file          = f,
                original_name = f.name,
            )

        messages.success(request, f'Event "{title}" has been updated.')

    return redirect('events_trainings')


# ── Delete ─────────────────────────────────────────────────────────────────────

@login_required
def event_delete(request, pk):
    from .models import Event

    event = get_object_or_404(Event, pk=pk)

    if not _can_manage_events(request.user):
        messages.error(request, 'You do not have permission to delete events.')
        return redirect('events_trainings')

    if request.method == 'POST':
        title = event.title
        # Delete physical attachment files before deleting the record
        for att in event.attachments.all():
            att.file.delete(save=False)
            att.delete()
        event.delete()
        messages.success(request, f'Event "{title}" has been deleted.')

    return redirect('events_trainings')


# ── Status toggle (AJAX) ───────────────────────────────────────────────────────

@login_required
def event_toggle_status(request, pk):
    """
    AJAX endpoint.
    Accepted POST actions: publish | draft | archive | unarchive
    Returns JSON { success, status, label } or { success, error }.
    """
    from .models import Event

    if not _can_manage_events(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    event  = get_object_or_404(Event, pk=pk)
    action = request.POST.get('action', '')

    if action == 'publish':
        event.status = Event.STATUS_PUBLISHED
    elif action == 'draft':
        event.status = Event.STATUS_DRAFT
    elif action == 'archive':
        event.status = Event.STATUS_ARCHIVED
    elif action == 'unarchive':
        # Restore to published if it was published before, otherwise draft
        event.status = Event.STATUS_PUBLISHED if getattr(event, 'published_at', None) else Event.STATUS_DRAFT
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    event.save()
    return JsonResponse({
        'success': True,
        'status':  event.status,
        'label':   event.get_status_display(),
    })


# ── Attachment delete (AJAX, optional) ────────────────────────────────────────

@login_required
def event_attachment_delete(request, pk):
    """
    Optional AJAX endpoint to delete a single attachment by its pk.
    POST { attachment_id: <int> }
    """
    from .models import EventAttachment

    if not _can_manage_events(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    att = get_object_or_404(EventAttachment, pk=pk)
    att.file.delete(save=False)
    att.delete()
    return JsonResponse({'success': True})






# ── Permission helper ──────────────────────────────────────────────────────────

def _can_manage_trainings(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('events_trainings')


# ── List view ──────────────────────────────────────────────────────────────────

@login_required
def trainings(request):
    # The trainings page has been merged into events_trainings.
    # Preserve any training-specific filter params and show the trainings tab.
    params = request.GET.copy()
    if 'search' in params:
        params['tr_search'] = params.pop('search')
    if 'status' in params:
        params['tr_status'] = params.pop('status')
    if 'month' in params:
        params['tr_month'] = params.pop('month')
    if 'per_page' in params:
        params['tr_per_page'] = params.pop('per_page')
    if 'page' in params:
        params['page_tr'] = params.pop('page')
    params['tab'] = 'tr'
    return redirect(f"{reverse('events_trainings')}?{params.urlencode()}")


# ── Create ─────────────────────────────────────────────────────────────────────

@login_required
def training_create(request):
    from .models import Training, TrainingAttachment

    if not _can_manage_trainings(request.user):
        messages.error(request, 'You do not have permission to create trainings.')
        return redirect(f"{reverse('events_trainings')}?tab=tr")

    if request.method == 'POST':
        title               = request.POST.get('title', '').strip()
        location            = request.POST.get('location', '').strip()
        summary             = request.POST.get('summary', '').strip()
        details             = request.POST.get('details', '').strip()
        organizer           = request.POST.get('organizer', '').strip()
        target_participants = request.POST.get('target_participants', '').strip()
        requirements        = request.POST.get('requirements', '').strip()
        contact_details     = request.POST.get('contact_details', '').strip()
        status              = request.POST.get('status', 'draft')
        start_date          = request.POST.get('start_date', '') or None
        end_date            = request.POST.get('end_date', '')   or None
        start_time          = request.POST.get('start_time', '') or None
        end_time            = request.POST.get('end_time', '')   or None
        archive_policy      = request.POST.get('archive_policy', 'default')
        archive_date        = request.POST.get('archive_date', '') or None

        errors = []
        if not title:               errors.append('Title is required.')
        if not location:            errors.append('Location is required.')
        if not details:             errors.append('Details are required.')
        if not organizer:           errors.append('Organizer is required.')
        if not target_participants: errors.append('Target participants is required.')
        if not start_date:          errors.append('Start date is required.')
        if status not in ('draft', 'published'):
            status = 'draft'

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(f"{reverse('events_trainings')}?tab=tr")

        training = Training(
            title               = title,
            location            = location,
            summary             = summary,
            details             = details,
            organizer           = organizer,
            target_participants = target_participants,
            requirements        = requirements,
            contact_details     = contact_details,
            status              = status,
            start_date          = start_date,
            end_date            = end_date,
            start_time          = start_time,
            end_time            = end_time,
            archive_policy      = archive_policy,
            archive_date        = archive_date,
            author              = request.user,
        )
        training.save()

        for f in request.FILES.getlist('attachments'):
            TrainingAttachment.objects.create(
                training      = training,
                file          = f,
                original_name = f.name,
            )

        verb = 'published' if status == 'published' else 'saved as draft'
        messages.success(request, f'Training "{title}" has been {verb}.')

    return redirect(f"{reverse('events_trainings')}?tab=tr")


# ── Edit ───────────────────────────────────────────────────────────────────────

@login_required
def training_edit(request, pk):
    from .models import Training, TrainingAttachment

    training = get_object_or_404(Training, pk=pk)

    if not _can_manage_trainings(request.user):
        messages.error(request, 'You do not have permission to edit trainings.')
        return redirect(f"{reverse('events_trainings')}?tab=tr")

    if request.method == 'POST':
        title               = request.POST.get('title', '').strip()
        location            = request.POST.get('location', '').strip()
        summary             = request.POST.get('summary', '').strip()
        details             = request.POST.get('details', '').strip()
        organizer           = request.POST.get('organizer', '').strip()
        target_participants = request.POST.get('target_participants', '').strip()
        requirements        = request.POST.get('requirements', '').strip()
        contact_details     = request.POST.get('contact_details', '').strip()
        status              = request.POST.get('status', training.status)
        start_date          = request.POST.get('start_date', '') or None
        end_date            = request.POST.get('end_date', '')   or None
        start_time          = request.POST.get('start_time', '') or None
        end_time            = request.POST.get('end_time', '')   or None
        archive_policy      = request.POST.get('archive_policy', training.archive_policy)
        archive_date        = request.POST.get('archive_date', '') or None

        errors = []
        if not title:               errors.append('Title is required.')
        if not location:            errors.append('Location is required.')
        if not details:             errors.append('Details are required.')
        if not organizer:           errors.append('Organizer is required.')
        if not target_participants: errors.append('Target participants is required.')
        if not start_date:          errors.append('Start date is required.')
        if status not in ('draft', 'published', 'archived'):
            status = training.status

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(f"{reverse('events_trainings')}?tab=tr")

        training.title               = title
        training.location            = location
        training.summary             = summary
        training.details             = details
        training.organizer           = organizer
        training.target_participants = target_participants
        training.requirements        = requirements
        training.contact_details     = contact_details
        training.status              = status
        training.start_date          = start_date
        training.end_date            = end_date
        training.start_time          = start_time
        training.end_time            = end_time
        training.archive_policy      = archive_policy
        training.archive_date        = archive_date
        training.save()

        for f in request.FILES.getlist('attachments'):
            TrainingAttachment.objects.create(
                training      = training,
                file          = f,
                original_name = f.name,
            )

        messages.success(request, f'Training "{title}" has been updated.')

    return redirect(f"{reverse('events_trainings')}?tab=tr")


# ── Delete ─────────────────────────────────────────────────────────────────────

@login_required
def training_delete(request, pk):
    from .models import Training

    training = get_object_or_404(Training, pk=pk)

    if not _can_manage_trainings(request.user):
        messages.error(request, 'You do not have permission to delete trainings.')
        return redirect(f"{reverse('events_trainings')}?tab=tr")

    if request.method == 'POST':
        title = training.title
        for att in training.attachments.all():
            att.file.delete(save=False)
            att.delete()
        training.delete()
        messages.success(request, f'Training "{title}" has been deleted.')

    return redirect(f"{reverse('events_trainings')}?tab=tr")


# ── Status toggle (AJAX) ───────────────────────────────────────────────────────

@login_required
def training_toggle_status(request, pk):
    from .models import Training

    if not _can_manage_trainings(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    training = get_object_or_404(Training, pk=pk)
    action   = request.POST.get('action', '')

    if action == 'publish':
        training.status = Training.STATUS_PUBLISHED
    elif action == 'draft':
        training.status = Training.STATUS_DRAFT
    elif action == 'archive':
        training.status = Training.STATUS_ARCHIVED
    elif action == 'unarchive':
        training.status = Training.STATUS_PUBLISHED if getattr(training, 'published_at', None) else Training.STATUS_DRAFT
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    training.save()
    return JsonResponse({
        'success': True,
        'status':  training.status,
        'label':   training.get_status_display(),
    })


# ── Permission helper ──────────────────────────────────────────────────────────
 
def _can_manage_issuances(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('issuances')
 
 
# ── List view ──────────────────────────────────────────────────────────────────
 
@login_required
def issuances(request):
    from .models import Issuance, IssuanceCategory

    can_manage = _can_manage_issuances(request.user)
    active_tab = request.GET.get('tab', 'issuances')

    search_query    = request.GET.get('search', '').strip()
    status_filter   = request.GET.get('status', '')
    category_filter = request.GET.get('category', '')
    month_filter    = request.GET.get('month', '')

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in (5, 10, 20, 40, 100):
        per_page = 10

    qs = (
        Issuance.objects
        .select_related('category', 'author')
        .order_by('-issuance_date', '-created_at')
    )

    if not can_manage:
        qs = qs.filter(status='published')
        status_filter = ''

    if search_query:
        qs = qs.filter(
            Q(issuance_no__icontains=search_query) |
            Q(summary__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    if can_manage and status_filter in ('draft', 'published', 'archived'):
        qs = qs.filter(status=status_filter)

    if category_filter:
        qs = qs.filter(category_id=category_filter)

    month_filter_label = ''
    if month_filter:
        try:
            year, month = month_filter.split('-')
            qs = qs.filter(issuance_date__year=int(year), issuance_date__month=int(month))
            import datetime
            month_filter_label = datetime.date(int(year), int(month), 1).strftime('%B %Y')
        except (ValueError, AttributeError):
            month_filter = ''

    all_dates = Issuance.objects.dates('issuance_date', 'month', order='DESC')
    available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in all_dates
    ]

    if can_manage:
        total_count     = Issuance.objects.count()
        published_count = Issuance.objects.filter(status='published').count()
        draft_count     = Issuance.objects.filter(status='draft').count()
        archived_count  = Issuance.objects.filter(status='archived').count()
    else:
        total_count     = Issuance.objects.filter(status='published').count()
        published_count = total_count
        draft_count     = None
        archived_count  = None

    from django.core.paginator import Paginator
    paginator   = Paginator(qs, per_page)
    page_number = request.GET.get('page', '').strip() or 1
    page_obj    = paginator.get_page(page_number)

    cat_search = request.GET.get('cat_search', '').strip()
    categories_qs = IssuanceCategory.objects.all()
    if cat_search:
        categories_qs = categories_qs.filter(name__icontains=cat_search)

    all_categories = IssuanceCategory.objects.all()

    if active_tab not in ('issuances', 'categories'):
        active_tab = 'issuances'
    if not can_manage and active_tab == 'categories':
        active_tab = 'issuances'

    can_view = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('issuances')
    )

    return render(request, 'issuances.html', {
        'active_tab':         active_tab,
        'can_manage':         can_manage,
        'can_view':           can_view,
        'issuances':          page_obj,
        'search_query':       search_query,
        'status_filter':      status_filter,
        'category_filter':    category_filter,
        'month_filter':       month_filter,
        'month_filter_label': month_filter_label,
        'available_months':   available_months,
        'per_page':           per_page,
        'total_count':        total_count,
        'published_count':    published_count,
        'draft_count':        draft_count,
        'archived_count':     archived_count,
        'categories':         categories_qs,
        'all_categories':     all_categories,
        'cat_search':         cat_search,
    }) 
 
# ── Create ─────────────────────────────────────────────────────────────────────
 
@login_required
def issuance_create(request):
    from .models import Issuance, IssuanceCategory
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to create issuances.')
        return redirect('issuances')
 
    if request.method == 'POST':
        issuance_no    = request.POST.get('issuance_no', '').strip()
        category_pk    = request.POST.get('category', '')
        issuance_date  = request.POST.get('issuance_date', '') or None
        summary        = request.POST.get('summary', '').strip()
        status         = request.POST.get('status', 'draft')
        archive_policy = request.POST.get('archive_policy', 'default')
        archive_date   = request.POST.get('archive_date', '') or None
        attachment     = request.FILES.get('attachment')
 
        errors = []
        if not issuance_no:   errors.append('Issuance No. is required.')
        if not category_pk:   errors.append('Category is required.')
        if not issuance_date: errors.append('Issuance Date is required.')
        if not summary:       errors.append('Summary is required.')
        if not attachment:    errors.append('Attachment is required.')
        if status not in ('draft', 'published'):
            status = 'draft'
 
        category = None
        if category_pk:
            try:
                category = IssuanceCategory.objects.get(pk=category_pk)
            except IssuanceCategory.DoesNotExist:
                errors.append('Selected category does not exist.')
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('issuances')
 
        issuance = Issuance(
            issuance_no    = issuance_no,
            category       = category,
            issuance_date  = issuance_date,
            summary        = summary,
            status         = status,
            archive_policy = archive_policy,
            archive_date   = archive_date,
            author         = request.user,
        )
        if attachment:
            issuance.attachment = attachment
        issuance.save()
 
        verb = 'published' if status == 'published' else 'saved as draft'
        messages.success(request, f'Issuance "{issuance_no}" has been {verb}.')
 
    return redirect('issuances')
 
 
# ── Edit ───────────────────────────────────────────────────────────────────────
 
@login_required
def issuance_edit(request, pk):
    from .models import Issuance, IssuanceCategory
    issuance = get_object_or_404(Issuance, pk=pk)
 
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to edit issuances.')
        return redirect('issuances')
 
    if request.method == 'POST':
        issuance_no    = request.POST.get('issuance_no', '').strip()
        category_pk    = request.POST.get('category', '')
        issuance_date  = request.POST.get('issuance_date', '') or None
        summary        = request.POST.get('summary', '').strip()
        status         = request.POST.get('status', issuance.status)
        archive_policy = request.POST.get('archive_policy', issuance.archive_policy)
        archive_date   = request.POST.get('archive_date', '') or None
        attachment     = request.FILES.get('attachment')
        clear_attachment = request.POST.get('clear_attachment') == '1'
 
        errors = []
        if not issuance_no:   errors.append('Issuance No. is required.')
        if not category_pk:   errors.append('Category is required.')
        if not issuance_date: errors.append('Issuance Date is required.')
        if not summary:       errors.append('Summary is required.')
        if status not in ('draft', 'published', 'archived'):
            status = issuance.status
 
        category = None
        if category_pk:
            try:
                category = IssuanceCategory.objects.get(pk=category_pk)
            except IssuanceCategory.DoesNotExist:
                errors.append('Selected category does not exist.')
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('issuances')
 
        issuance.issuance_no    = issuance_no
        issuance.category       = category
        issuance.issuance_date  = issuance_date
        issuance.summary        = summary
        issuance.status         = status
        issuance.archive_policy = archive_policy
        issuance.archive_date   = archive_date
 
        if clear_attachment and issuance.attachment:
            issuance.attachment.delete(save=False)
            issuance.attachment = None
        elif attachment:
            if issuance.attachment:
                issuance.attachment.delete(save=False)
            issuance.attachment = attachment
 
        issuance.save()
        messages.success(request, f'Issuance "{issuance_no}" has been updated.')
 
    return redirect('issuances')
 
 
# ── Delete ─────────────────────────────────────────────────────────────────────
 
@login_required
def issuance_delete(request, pk):
    from .models import Issuance
    issuance = get_object_or_404(Issuance, pk=pk)
 
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to delete issuances.')
        return redirect('issuances')
 
    if request.method == 'POST':
        no = issuance.issuance_no
        if issuance.attachment:
            issuance.attachment.delete(save=False)
        issuance.delete()
        messages.success(request, f'Issuance "{no}" has been deleted.')
 
    return redirect('issuances')
 
 
# ── Status toggle (AJAX) ───────────────────────────────────────────────────────
 
@login_required
def issuance_toggle_status(request, pk):
    from .models import Issuance
    if not _can_manage_issuances(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)
 
    issuance = get_object_or_404(Issuance, pk=pk)
    action   = request.POST.get('action', '')
 
    if action == 'publish':
        issuance.status = Issuance.STATUS_PUBLISHED
    elif action == 'draft':
        issuance.status = Issuance.STATUS_DRAFT
    elif action == 'archive':
        issuance.status = Issuance.STATUS_ARCHIVED
    elif action == 'unarchive':
        issuance.status = (
            Issuance.STATUS_PUBLISHED
            if getattr(issuance, 'published_at', None)
            else Issuance.STATUS_DRAFT
        )
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})
 
    issuance.save()
    return JsonResponse({
        'success': True,
        'status':  issuance.status,
        'label':   issuance.get_status_display(),
    })
 
 
# ── Category CRUD ──────────────────────────────────────────────────────────────
 
@login_required
def issuance_category_add(request):
    from .models import IssuanceCategory
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('issuances')
 
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Category name is required.')
            return redirect('issuances?tab=categories')
        if IssuanceCategory.objects.filter(name__iexact=name).exists():
            messages.error(request, f'Category "{name}" already exists.')
        else:
            IssuanceCategory.objects.create(name=name)
            messages.success(request, f'Category "{name}" has been created.')
 
    return redirect('/issuances/?tab=categories')
 
 
@login_required
def issuance_category_edit(request, pk):
    from .models import IssuanceCategory
    category = get_object_or_404(IssuanceCategory, pk=pk)
 
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('issuances')
 
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Category name is required.')
        elif IssuanceCategory.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            messages.error(request, f'Category "{name}" already exists.')
        else:
            category.name = name
            category.save()
            messages.success(request, f'Category updated to "{name}".')
 
    return redirect('/issuances/?tab=categories')
 
 
@login_required
def issuance_category_delete(request, pk):
    from .models import IssuanceCategory
    category = get_object_or_404(IssuanceCategory, pk=pk)
 
    if not _can_manage_issuances(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('issuances')
 
    if request.method == 'POST':
        if category.issuance_count > 0:
            messages.error(
                request,
                f'Cannot delete "{category.name}" — it has {category.issuance_count} '
                f'issuance(s) assigned. Reassign them first.'
            )
        else:
            name = category.name
            category.delete()
            messages.success(request, f'Category "{name}" has been deleted.')
 
    return redirect('/issuances/?tab=categories')


def _can_manage_wiki(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('wiki')
 
 
@login_required
def wiki(request):
    from .models import WikiArticle, WikiTag

    can_manage = _can_manage_wiki(request.user)
    active_tab = request.GET.get('tab', 'articles')

    search_query  = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    tag_filter    = request.GET.get('tag', '')
    month_filter  = request.GET.get('month', '')

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in (5, 10, 20, 40, 100):
        per_page = 10

    qs = (
        WikiArticle.objects
        .select_related('author')
        .prefetch_related('tags')
        .order_by('-created_at')
    )

    if not can_manage:
        qs = qs.filter(status='published')
        status_filter = ''

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(article__icontains=search_query) |
            Q(reference__icontains=search_query) |
            Q(tags__name__icontains=search_query)
        ).distinct()

    if can_manage and status_filter in ('draft', 'published', 'archived'):
        qs = qs.filter(status=status_filter)

    if tag_filter:
        qs = qs.filter(tags__pk=tag_filter)

    month_filter_label = ''
    if month_filter:
        try:
            year, month = month_filter.split('-')
            qs = qs.filter(created_at__year=int(year), created_at__month=int(month))
            import datetime
            month_filter_label = datetime.date(int(year), int(month), 1).strftime('%B %Y')
        except (ValueError, AttributeError):
            month_filter = ''

    all_dates = WikiArticle.objects.dates('created_at', 'month', order='DESC')
    available_months = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in all_dates
    ]

    if can_manage:
        total_count     = WikiArticle.objects.count()
        published_count = WikiArticle.objects.filter(status='published').count()
        draft_count     = WikiArticle.objects.filter(status='draft').count()
        archived_count  = WikiArticle.objects.filter(status='archived').count()
    else:
        total_count     = WikiArticle.objects.filter(status='published').count()
        published_count = total_count
        draft_count     = None
        archived_count  = None

    paginator   = Paginator(qs, per_page)
    page_number = request.GET.get('page', '').strip() or 1
    page_obj    = paginator.get_page(page_number)

    tag_search = request.GET.get('tag_search', '').strip()
    all_tags_qs = WikiTag.objects.all()
    all_tags_filtered = all_tags_qs.filter(name__icontains=tag_search) if tag_search else all_tags_qs

    if active_tab not in ('articles', 'tags'):
        active_tab = 'articles'
    if not can_manage and active_tab == 'tags':
        active_tab = 'articles'

    can_view = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('wiki')
    )

    return render(request, 'wiki.html', {
        'active_tab':         active_tab,
        'can_manage':         can_manage,
        'can_view':           can_view,
        'articles':           page_obj,
        'search_query':       search_query,
        'status_filter':      status_filter,
        'tag_filter':         tag_filter,
        'month_filter':       month_filter,
        'month_filter_label': month_filter_label,
        'available_months':   available_months,
        'per_page':           per_page,
        'total_count':        total_count,
        'published_count':    published_count,
        'draft_count':        draft_count,
        'archived_count':     archived_count,
        'all_tags':           all_tags_qs,
        'all_tags_filtered':  all_tags_filtered,
        'tag_search':         tag_search,
    }) 
 
def _resolve_tags(tags_input):
    """
    Parse a comma-separated string of tag names, get-or-create each WikiTag,
    and return a queryset-compatible list of PKs.
    """
    from .models import WikiTag
    pks = []
    for raw in tags_input.split(','):
        name = raw.strip()
        if name:
            tag, _ = WikiTag.objects.get_or_create(name=name)
            pks.append(tag.pk)
    return pks
 
 
@login_required
def wiki_create(request):
    from .models import WikiArticle
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to create wiki articles.')
        return redirect('wiki')
 
    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        article        = request.POST.get('article', '').strip()
        reference      = request.POST.get('reference', '').strip()
        tags_input     = request.POST.get('tags_input', '').strip()
        status         = request.POST.get('status', 'draft')
        archive_policy = request.POST.get('archive_policy', 'default')
        archive_date   = request.POST.get('archive_date', '') or None
 
        errors = []
        if not title:     errors.append('Title is required.')
        if not article:   errors.append('Article content is required.')
        if not reference: errors.append('Reference is required.')
        if not tags_input:errors.append('At least one tag is required.')
        if status not in ('draft', 'published'):
            status = 'draft'
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('wiki')
 
        wiki_article = WikiArticle(
            title          = title,
            article        = article,
            reference      = reference,
            status         = status,
            archive_policy = archive_policy,
            archive_date   = archive_date,
            author         = request.user,
        )
        wiki_article.save()
        wiki_article.tags.set(_resolve_tags(tags_input))
 
        verb = 'published' if status == 'published' else 'saved as draft'
        messages.success(request, f'Article "{title}" has been {verb}.')
 
    return redirect('wiki')
 
 
@login_required
def wiki_edit(request, pk):
    from .models import WikiArticle
    wiki_article = get_object_or_404(WikiArticle, pk=pk)
 
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to edit wiki articles.')
        return redirect('wiki')
 
    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        article        = request.POST.get('article', '').strip()
        reference      = request.POST.get('reference', '').strip()
        tags_input     = request.POST.get('tags_input', '').strip()
        status         = request.POST.get('status', wiki_article.status)
        archive_policy = request.POST.get('archive_policy', wiki_article.archive_policy)
        archive_date   = request.POST.get('archive_date', '') or None
 
        errors = []
        if not title:     errors.append('Title is required.')
        if not article:   errors.append('Article content is required.')
        if not reference: errors.append('Reference is required.')
        if not tags_input:errors.append('At least one tag is required.')
        if status not in ('draft', 'published', 'archived'):
            status = wiki_article.status
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('wiki')
 
        wiki_article.title          = title
        wiki_article.article        = article
        wiki_article.reference      = reference
        wiki_article.status         = status
        wiki_article.archive_policy = archive_policy
        wiki_article.archive_date   = archive_date
        wiki_article.save()
        wiki_article.tags.set(_resolve_tags(tags_input))
 
        messages.success(request, f'Article "{title}" has been updated.')
 
    return redirect('wiki')
 
 
@login_required
def wiki_delete(request, pk):
    from .models import WikiArticle
    wiki_article = get_object_or_404(WikiArticle, pk=pk)
 
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to delete wiki articles.')
        return redirect('wiki')
 
    if request.method == 'POST':
        title = wiki_article.title
        wiki_article.delete()
        messages.success(request, f'Article "{title}" has been deleted.')
 
    return redirect('wiki')
 
 
@login_required
def wiki_toggle_status(request, pk):
    from .models import WikiArticle
    if not _can_manage_wiki(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)
 
    wiki_article = get_object_or_404(WikiArticle, pk=pk)
    action       = request.POST.get('action', '')
 
    if action == 'publish':
        wiki_article.status = WikiArticle.STATUS_PUBLISHED
    elif action == 'draft':
        wiki_article.status = WikiArticle.STATUS_DRAFT
    elif action == 'archive':
        wiki_article.status = WikiArticle.STATUS_ARCHIVED
    elif action == 'unarchive':
        wiki_article.status = (
            WikiArticle.STATUS_PUBLISHED
            if getattr(wiki_article, 'published_at', None)
            else WikiArticle.STATUS_DRAFT
        )
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})
 
    wiki_article.save()
    return JsonResponse({
        'success': True,
        'status':  wiki_article.status,
        'label':   wiki_article.get_status_display(),
    })
 
 
# ── Tag CRUD ───────────────────────────────────────────────────────────────────
 
@login_required
def wiki_tag_add(request):
    from .models import WikiTag
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('wiki')
 
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Tag name is required.')
        elif WikiTag.objects.filter(name__iexact=name).exists():
            messages.error(request, f'Tag "{name}" already exists.')
        else:
            WikiTag.objects.create(name=name)
            messages.success(request, f'Tag "{name}" has been created.')
 
    return redirect('/wiki/?tab=tags')
 
 
@login_required
def wiki_tag_edit(request, pk):
    from .models import WikiTag
    tag = get_object_or_404(WikiTag, pk=pk)
 
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('wiki')
 
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Tag name is required.')
        elif WikiTag.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            messages.error(request, f'Tag "{name}" already exists.')
        else:
            tag.name = name
            tag.save()
            messages.success(request, f'Tag updated to "{name}".')
 
    return redirect('/wiki/?tab=tags')
 
 
@login_required
def wiki_tag_delete(request, pk):
    from .models import WikiTag
    tag = get_object_or_404(WikiTag, pk=pk)
 
    if not _can_manage_wiki(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('wiki')
 
    if request.method == 'POST':
        name = tag.name
        tag.delete()   # ManyToMany entries auto-cleaned; articles are kept
        messages.success(request, f'Tag "{name}" has been deleted.')
 
    return redirect('/wiki/?tab=tags')



# Settings Views

GENDER_OPTIONS = [
    ('male',         'Male',              'fa-solid fa-mars'),
    ('female',       'Female',            'fa-solid fa-venus'),
    ('non_binary',   'Non-Binary',        'fa-solid fa-venus-mars'),
    ('prefer_not',   'Prefer not to say', 'fa-solid fa-user-shield'),
    ('self_describe','Let me describe',   'fa-solid fa-pen'),
]
 
 
@login_required
def settings_profile(request):
    profile = request.user.profile
 
    if request.method == 'POST':
        # Handle avatar deletion
        if 'clear_avatar' in request.POST:
            if profile.avatar:
                profile.avatar.delete(save=False)
                profile.avatar = None
                profile.save()
            messages.success(request, 'Avatar removed successfully.')
            return redirect('settings_profile')
 
        # Update User fields
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
 
        if not first_name or not last_name:
            messages.error(request, 'First name and last name are required.')
            return redirect('settings_profile')
 
        request.user.first_name = first_name
        request.user.last_name  = last_name
        request.user.email      = email
        request.user.save()
 
        # Update Profile fields
        profile.middle_name   = request.POST.get('middle_name', '').strip()
        profile.position      = request.POST.get('position', '').strip()
        profile.department    = request.POST.get('department', '').strip()
        profile.mobile_number = request.POST.get('mobile_number', '').strip()
        profile.bio           = request.POST.get('bio', '').strip()
 
        gender = request.POST.get('gender', '').strip()
        valid_gender_values = [v for v, *_ in GENDER_OPTIONS]
        profile.gender = gender if gender in valid_gender_values else ''
        if profile.gender == 'self_describe':
            profile.gender_self_describe = request.POST.get('gender_self_describe', '').strip()
        else:
            profile.gender_self_describe = ''
 
        # Avatar upload
        new_avatar = request.FILES.get('avatar')
        if new_avatar:
            if profile.avatar:
                profile.avatar.delete(save=False)
            profile.avatar = new_avatar
 
        profile.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('settings_profile')
 
    return render(request, 'settings.html', {
        'gender_options':     GENDER_OPTIONS,
        'department_choices': DEPARTMENT_CHOICES,
    })
 
 
@login_required
def settings_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password     = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
 
        if not request.user.check_password(current_password):
            messages.error(request, 'Your current password is incorrect.')
            return redirect('settings_profile')   # redirects back; JS will show toast
 
        if len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
            return redirect('settings_profile')
 
        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('settings_profile')
 
        request.user.set_password(new_password)
        request.user.save()
 
        # Keep the user logged in after password change
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, request.user)
 
        messages.success(request, 'Your password has been updated successfully.')
        return redirect('settings_profile')
 
    return redirect('settings_profile')


def _has_corner_access(user):
    if user.is_superuser:
        return True
    return hasattr(user, 'profile') and user.profile.has_module_access('employees_corner')


def _can_manage_corner(user):
    if user.is_superuser:
        return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('employees_corner')


def _month_choices_for_posts(queryset):
    return [
        {
            'value': dt.strftime('%Y-%m'),
            'label': dt.strftime('%b %Y')
        }
        for dt in queryset.order_by('-date_posted').dates('date_posted', 'month', order='DESC')
    ]


def _apply_post_filters(queryset, search_query, month_filter, status_filter):
    if status_filter in ('published', 'draft', 'archived'):
        queryset = queryset.filter(status=status_filter)

    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query) |
            Q(summary__icontains=search_query) |
            Q(content__icontains=search_query)
        )

    if month_filter:
        try:
            year, month = month_filter.split('-')
            queryset = queryset.filter(date_posted__year=int(year), date_posted__month=int(month))
        except (ValueError, TypeError):
            pass

    return queryset


def employees_corner(request):
    if not _has_corner_access(request.user):
        return render(request, 'permission_denied.html')

    can_manage = _can_manage_corner(request.user)

    active_tab  = request.GET.get('tab', 'union')
    inner_union = request.GET.get('inner_union', 'postings')
    inner_coop  = request.GET.get('inner_coop', 'postings')

    union_status_filter = request.GET.get('union_status', '')
    coop_status_filter  = request.GET.get('coop_status', '')

    union_search_query = request.GET.get('union_search', '').strip()
    coop_search_query  = request.GET.get('coop_search', '').strip()

    union_month_filter = request.GET.get('union_month', '')
    coop_month_filter  = request.GET.get('coop_month', '')

    try:
        union_per_page = int(request.GET.get('union_per_page', 10))
    except ValueError:
        union_per_page = 10

    try:
        coop_per_page = int(request.GET.get('coop_per_page', 10))
    except ValueError:
        coop_per_page = 10

    union_page = request.GET.get('page_union', 1)
    coop_page  = request.GET.get('page_coop', 1)

    union_base_qs = EmployeeCornerPost.objects.filter(category=EmployeeCornerPost.CATEGORY_UNION)
    coop_base_qs  = EmployeeCornerPost.objects.filter(category=EmployeeCornerPost.CATEGORY_COOP)

    if not can_manage:
        union_status_filter = ''
        coop_status_filter  = ''
        union_posts_qs = _apply_post_filters(
            union_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED),
            union_search_query, union_month_filter, ''
        )
        coop_posts_qs = _apply_post_filters(
            coop_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED),
            coop_search_query, coop_month_filter, ''
        )
    else:
        union_posts_qs = _apply_post_filters(union_base_qs, union_search_query, union_month_filter, union_status_filter)
        coop_posts_qs  = _apply_post_filters(coop_base_qs,  coop_search_query,  coop_month_filter,  coop_status_filter)

    union_paginator = Paginator(union_posts_qs, union_per_page)
    coop_paginator  = Paginator(coop_posts_qs,  coop_per_page)

    union_posts = union_paginator.get_page(union_page)
    coop_posts  = coop_paginator.get_page(coop_page)

    union_posts_with_files = union_base_qs.prefetch_related('attachments').filter(attachments__isnull=False).distinct()
    coop_posts_with_files  = coop_base_qs.prefetch_related('attachments').filter(attachments__isnull=False).distinct()

    if can_manage:
        union_published_count = union_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED).count()
        union_draft_count     = union_base_qs.filter(status=EmployeeCornerPost.STATUS_DRAFT).count()
        union_archived_count  = union_base_qs.filter(status=EmployeeCornerPost.STATUS_ARCHIVED).count()
        union_total_count     = union_base_qs.count()
        coop_published_count  = coop_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED).count()
        coop_draft_count      = coop_base_qs.filter(status=EmployeeCornerPost.STATUS_DRAFT).count()
        coop_archived_count   = coop_base_qs.filter(status=EmployeeCornerPost.STATUS_ARCHIVED).count()
        coop_total_count      = coop_base_qs.count()
    else:
        union_published_count = union_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED).count()
        union_draft_count     = None
        union_archived_count  = None
        union_total_count     = union_published_count
        coop_published_count  = coop_base_qs.filter(status=EmployeeCornerPost.STATUS_PUBLISHED).count()
        coop_draft_count      = None
        coop_archived_count   = None
        coop_total_count      = coop_published_count

    context = {
        'active_tab':  active_tab,
        'inner_union': inner_union,
        'inner_coop':  inner_coop,
        'can_manage':  can_manage,

        'union_total_count':      union_total_count,
        'union_post_count':       union_base_qs.count(),
        'union_published_count':  union_published_count,
        'union_draft_count':      union_draft_count,
        'union_archived_count':   union_archived_count,
        'union_file_count':       PostAttachment.objects.filter(post__category=EmployeeCornerPost.CATEGORY_UNION).count(),
        'union_posts':            union_posts,
        'union_posts_with_files': union_posts_with_files,
        'union_search_query':     union_search_query,
        'union_month_filter':     union_month_filter,
        'union_available_months': _month_choices_for_posts(union_base_qs),
        'union_status_filter':    union_status_filter,
        'union_per_page':         union_per_page,

        'coop_total_count':      coop_total_count,
        'coop_post_count':       coop_base_qs.count(),
        'coop_published_count':  coop_published_count,
        'coop_draft_count':      coop_draft_count,
        'coop_archived_count':   coop_archived_count,
        'coop_file_count':       PostAttachment.objects.filter(post__category=EmployeeCornerPost.CATEGORY_COOP).count(),
        'coop_posts':            coop_posts,
        'coop_posts_with_files': coop_posts_with_files,
        'coop_search_query':     coop_search_query,
        'coop_month_filter':     coop_month_filter,
        'coop_available_months': _month_choices_for_posts(coop_base_qs),
        'coop_status_filter':    coop_status_filter,
        'coop_per_page':         coop_per_page,
    }

    return render(request, 'employees_corner.html', context)

def _normalize_section(section):
    return section if section in (EmployeeCornerPost.CATEGORY_UNION, EmployeeCornerPost.CATEGORY_COOP) else EmployeeCornerPost.CATEGORY_UNION


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _create_or_update_post(request, section, post=None):
    title = request.POST.get('title', '').strip()
    summary = request.POST.get('summary', '').strip()
    content = request.POST.get('content', '').strip()
    status = request.POST.get('status', EmployeeCornerPost.STATUS_DRAFT)
    date_posted = _parse_date(request.POST.get('date_posted'))
    archive_policy = request.POST.get('archive_policy', EmployeeCornerPost.ARCHIVE_DEFAULT)
    archive_date = _parse_date(request.POST.get('archive_date'))

    if status not in (EmployeeCornerPost.STATUS_DRAFT, EmployeeCornerPost.STATUS_PUBLISHED, EmployeeCornerPost.STATUS_ARCHIVED):
        status = EmployeeCornerPost.STATUS_DRAFT

    if archive_policy not in (EmployeeCornerPost.ARCHIVE_DEFAULT, EmployeeCornerPost.ARCHIVE_ON_DATE, EmployeeCornerPost.ARCHIVE_NEVER):
        archive_policy = EmployeeCornerPost.ARCHIVE_DEFAULT

    if not title or not content:
        return None, 'Title and content are required.'

    creating = post is None
    if creating:
        post = EmployeeCornerPost(category=section, author=request.user)

    post.title = title
    post.summary = summary
    post.content = content
    post.status = status
    # Set date_posted automatically on creation if not provided; on edit, only
    # update date_posted when the form explicitly supplies a value.
    if creating:
        post.date_posted = date_posted or datetime.date.today()
    else:
        if date_posted:
            post.date_posted = date_posted
    post.archive_policy = archive_policy
    post.archive_date = archive_date
    post.author = request.user
    post.save()

    for file_obj in request.FILES.getlist('attachments'):
        PostAttachment.objects.create(post=post, file=file_obj, original_name=file_obj.name)

    return post, None


def corner_post_create(request, section):
    if request.method != 'POST':
        return redirect('employees_corner')
    if not _can_manage_corner(request.user):
        return render(request, 'permission_denied.html')

    section = _normalize_section(section)
    post, error = _create_or_update_post(request, section)

    if error:
        messages.error(request, error)
    else:
        messages.success(request, f'New {section.title()} post has been created.')

    return redirect(f"{reverse('employees_corner')}?tab={section}&inner_{section}=postings")


def corner_post_edit(request, section, pk):
    if request.method != 'POST':
        return redirect('employees_corner')
    if not _can_manage_corner(request.user):
        return render(request, 'permission_denied.html')

    section = _normalize_section(section)
    post = get_object_or_404(EmployeeCornerPost, pk=pk, category=section)
    post, error = _create_or_update_post(request, section, post=post)

    if error:
        messages.error(request, error)
    else:
        messages.success(request, f'{section.title()} post has been updated.')

    return redirect(f"{reverse('employees_corner')}?tab={section}&inner_{section}=postings")


def corner_post_delete(request, section, pk):
    if request.method != 'POST':
        return redirect('employees_corner')
    if not _can_manage_corner(request.user):
        return render(request, 'permission_denied.html')

    section = _normalize_section(section)
    post = get_object_or_404(EmployeeCornerPost, pk=pk, category=section)
    post.delete()
    messages.success(request, f'{section.title()} post has been deleted.')
    return redirect(f"{reverse('employees_corner')}?tab={section}&inner_{section}=postings")


def corner_post_toggle_status(request, section, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)
    if not _can_manage_corner(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    section = _normalize_section(section)
    post = get_object_or_404(EmployeeCornerPost, pk=pk, category=section)
    action = request.POST.get('action', '')

    if action == 'publish':
        post.status = EmployeeCornerPost.STATUS_PUBLISHED
    elif action == 'draft':
        post.status = EmployeeCornerPost.STATUS_DRAFT
    elif action == 'archive':
        post.status = EmployeeCornerPost.STATUS_ARCHIVED
    elif action == 'unarchive':
        post.status = (EmployeeCornerPost.STATUS_PUBLISHED
                       if post.published_at else EmployeeCornerPost.STATUS_DRAFT)
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'}, status=400)

    post.save()
    return JsonResponse({'success': True, 'status': post.status, 'label': post.get_status_display()})




# ── Permission helper ──────────────────────────────────────────────────────────
def _can_manage(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.profile.can_edit_module('applications')
    except Exception:
        return False
 
 
# ── List / main view ───────────────────────────────────────────────────────────
@login_required
def applications(request):
    qs = Application.objects.select_related('author').all()
 
    # ---- Status filter (stat cards)
    status_filter = request.GET.get('status', '').strip()
    if status_filter in ('draft', 'published'):
        qs = qs.filter(status=status_filter)
 
    # ---- Search
    search_query = request.GET.get('search', '').strip()
    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(url__icontains=search_query)
        )
 
    # ---- Counts (before pagination, after filters except status)
    base_qs        = Application.objects.all()
    total_count    = base_qs.count()
    published_count = base_qs.filter(status='published').count()
    draft_count     = base_qs.filter(status='draft').count()
 
    # ---- Per-page
    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in (5, 10, 20, 40, 100):
            per_page = 10
    except ValueError:
        per_page = 10
 
    paginator   = Paginator(qs, per_page)
    page_number = request.GET.get('page', 1)
    apps_page   = paginator.get_page(page_number)
 
    ctx = {
        'applications':    apps_page,
        'total_count':     total_count,
        'published_count': published_count,
        'draft_count':     draft_count,
        'status_filter':   status_filter,
        'search_query':    search_query,
        'per_page':        per_page,
        'can_manage':      _can_manage(request.user),
    }
    return render(request, 'applications.html', ctx)
 
 
# ── Create ─────────────────────────────────────────────────────────────────────
@login_required
def application_create(request):
    if not _can_manage(request.user):
        messages.error(request, 'You do not have permission to add applications.')
        return redirect('applications')
 
    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        url         = request.POST.get('url', '').strip()
        description = request.POST.get('description', '').strip()
        status      = request.POST.get('status', 'draft')
        logo        = request.FILES.get('logo')
 
        errors = []
        if not title:       errors.append('Title is required.')
        if not url:         errors.append('URL is required.')
        if not description: errors.append('Short description is required.')
        if not logo:        errors.append('Logo is required.')
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('applications')
 
        from django.utils import timezone
        app = Application(
            title=title, url=url, description=description,
            status=status, logo=logo, author=request.user,
        )
        if status == 'published':
            app.published_at = timezone.now()
        app.save()
 
        messages.success(request, f'"{title}" has been created.')
    return redirect('applications')
 
 
# ── Edit ───────────────────────────────────────────────────────────────────────
@login_required
def application_edit(request, pk):
    if not _can_manage(request.user):
        messages.error(request, 'You do not have permission to edit applications.')
        return redirect('applications')
 
    app = get_object_or_404(Application, pk=pk)
 
    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        url         = request.POST.get('url', '').strip()
        description = request.POST.get('description', '').strip()
        status      = request.POST.get('status', app.status)
        logo        = request.FILES.get('logo')
        clear_logo  = request.POST.get('clear_logo') == '1'
 
        errors = []
        if not title:       errors.append('Title is required.')
        if not url:         errors.append('URL is required.')
        if not description: errors.append('Short description is required.')
 
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('applications')
 
        app.title       = title
        app.url         = url
        app.description = description
 
        # Status transition
        from django.utils import timezone
        if status == 'published' and app.status != 'published':
            app.published_at = timezone.now()
        app.status = status
 
        # Logo handling
        if clear_logo and not logo:
            if app.logo:
                app.logo.delete(save=False)
                app.logo = None
        elif logo:
            if app.logo:
                app.logo.delete(save=False)
            app.logo = logo
 
        app.save()
        messages.success(request, f'"{app.title}" has been updated.')
 
    return redirect('applications')
 
 
# ── Delete ─────────────────────────────────────────────────────────────────────
@login_required
def application_delete(request, pk):
    if not _can_manage(request.user):
        messages.error(request, 'You do not have permission to delete applications.')
        return redirect('applications')
 
    app = get_object_or_404(Application, pk=pk)
    if request.method == 'POST':
        title = app.title
        if app.logo:
            app.logo.delete(save=False)
        app.delete()
        messages.success(request, f'"{title}" has been deleted.')
    return redirect('applications')
 
 
# ── Toggle status (AJAX) ───────────────────────────────────────────────────────
@login_required
def application_toggle_status(request, pk):
    if not _can_manage(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
 
    app = get_object_or_404(Application, pk=pk)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)
 
    action = request.POST.get('action', '')
 
    from django.utils import timezone
    if action == 'publish':
        app.status = 'published'
        if not app.published_at:
            app.published_at = timezone.now()
        app.save()
    elif action == 'draft':
        app.status = 'draft'
        app.save()
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'}, status=400)
 
    return JsonResponse({'success': True, 'status': app.status})


# ── Directory ──────────────────────────────────────────────────────────────────
from .models import Office

def _can_manage_directory(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('directory')


@login_required
def directory(request):
    active_tab = request.GET.get('tab', 'employees')

    # ── EMPLOYEES tab ──────────────────────────────────────────────────────────
    emp_search = request.GET.get('emp_search', '').strip()
    emp_dept   = request.GET.get('emp_dept', '').strip()

    try:
        emp_per_page = int(request.GET.get('emp_per_page', 20))
    except (ValueError, TypeError):
        emp_per_page = 20
    if emp_per_page not in (10, 20, 40, 100):
        emp_per_page = 20

    emp_qs = (
        UserProfile.objects
        .select_related('user', 'role')
        .filter(user__is_superuser=False, user__is_active=True)
        .order_by('user__last_name', 'user__first_name')
    )

    if emp_search:
        emp_qs = emp_qs.filter(
            Q(user__first_name__icontains=emp_search) |
            Q(user__last_name__icontains=emp_search)  |
            Q(user__email__icontains=emp_search)       |
            Q(mobile_number__icontains=emp_search)     |
            Q(position__icontains=emp_search)          |
            Q(department__icontains=emp_search)
        )

    if emp_dept:
        emp_qs = emp_qs.filter(department__icontains=emp_dept)

    emp_total = UserProfile.objects.filter(user__is_superuser=False, user__is_active=True).count()

    emp_paginator   = Paginator(emp_qs, emp_per_page)
    emp_page_number = request.GET.get('page_emp', '').strip() or 1
    emp_page_obj    = emp_paginator.get_page(emp_page_number)

    # Distinct departments for the filter dropdown
    dept_values = (
        UserProfile.objects
        .filter(user__is_superuser=False, user__is_active=True)
        .exclude(department='')
        .values_list('department', flat=True)
        .distinct()
        .order_by('department')
    )

    # ── OFFICES tab ────────────────────────────────────────────────────────────
    off_search = request.GET.get('off_search', '').strip()

    try:
        off_per_page = int(request.GET.get('off_per_page', 20))
    except (ValueError, TypeError):
        off_per_page = 20
    if off_per_page not in (10, 20, 40, 100):
        off_per_page = 20

    off_qs = Office.objects.all()

    if off_search:
        off_qs = off_qs.filter(
            Q(name__icontains=off_search) |
            Q(local_number__icontains=off_search)
        )

    off_total     = Office.objects.count()
    off_paginator = Paginator(off_qs, off_per_page)
    off_page_obj  = off_paginator.get_page(request.GET.get('page_off', '').strip() or 1)

    can_manage = _can_manage_directory(request.user)
    can_view   = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('directory')
    )

    if active_tab not in ('employees', 'offices'):
        active_tab = 'employees'

    return render(request, 'directory.html', {
        'active_tab':    active_tab,
        'can_manage':    can_manage,
        'can_view':      can_view,
        # employees
        'employees':     emp_page_obj,
        'emp_search':    emp_search,
        'emp_dept':      emp_dept,
        'emp_per_page':  emp_per_page,
        'emp_total':     emp_total,
        'dept_values':   dept_values,
        # offices
        'offices':       off_page_obj,
        'off_search':    off_search,
        'off_per_page':  off_per_page,
        'off_total':     off_total,
    })


@login_required
def office_add(request):
    if not _can_manage_directory(request.user):
        messages.error(request, 'You do not have permission to manage offices.')
        return redirect('directory')

    if request.method == 'POST':
        name         = request.POST.get('name', '').strip()
        local_number = request.POST.get('local_number', '').strip()

        errors = []
        if not name:         errors.append('Office name is required.')
        if not local_number: errors.append('Local number is required.')

        if Office.objects.filter(name__iexact=name).exists():
            errors.append(f'An office named "{name}" already exists.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('/directory/?tab=offices')

        Office.objects.create(name=name, local_number=local_number)
        messages.success(request, f'Office "{name}" has been added.')

    return redirect('/directory/?tab=offices')


@login_required
def office_edit(request, pk):
    office = get_object_or_404(Office, pk=pk)

    if not _can_manage_directory(request.user):
        messages.error(request, 'You do not have permission to manage offices.')
        return redirect('directory')

    if request.method == 'POST':
        name         = request.POST.get('name', '').strip()
        local_number = request.POST.get('local_number', '').strip()

        errors = []
        if not name:         errors.append('Office name is required.')
        if not local_number: errors.append('Local number is required.')

        if Office.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            errors.append(f'An office named "{name}" already exists.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('/directory/?tab=offices')

        office.name         = name
        office.local_number = local_number
        office.save()
        messages.success(request, f'Office "{name}" has been updated.')

    return redirect('/directory/?tab=offices')


@login_required
def office_delete(request, pk):
    office = get_object_or_404(Office, pk=pk)

    if not _can_manage_directory(request.user):
        messages.error(request, 'You do not have permission to manage offices.')
        return redirect('directory')

    if request.method == 'POST':
        name = office.name
        office.delete()
        messages.success(request, f'Office "{name}" has been deleted.')

    return redirect('/directory/?tab=offices')



# ── Downloads ──────────────────────────────────────────────────────────────────
from .models import Download, DownloadCategory, DownloadTag

def _can_manage_downloads(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('downloads')


def _resolve_download_tags(tags_input):
    pks = []
    for raw in tags_input.split(','):
        name = raw.strip()
        if name:
            tag, _ = DownloadTag.objects.get_or_create(name=name)
            pks.append(tag.pk)
    return pks


@login_required
def downloads(request):
    active_tab = request.GET.get('tab', 'forms')
    if active_tab not in ('forms', 'files', 'categories', 'tags'):
        active_tab = 'forms'

    can_manage = _can_manage_downloads(request.user)
    can_view   = request.user.is_superuser or (
        hasattr(request.user, 'profile') and
        request.user.profile.has_module_access('downloads')
    )

    if active_tab in ('categories', 'tags') and not can_manage:
        active_tab = 'forms'

    def _build_tab(tab_key, request):
        search        = request.GET.get(f'{tab_key}_search', '').strip()
        status_filter = request.GET.get(f'{tab_key}_status', '')
        cat_filter    = request.GET.get(f'{tab_key}_cat', '')
        tag_filter    = request.GET.get(f'{tab_key}_tag', '')

        try:
            per_page = int(request.GET.get(f'{tab_key}_per_page', 10))
        except (ValueError, TypeError):
            per_page = 10
        if per_page not in (5, 10, 20, 40, 100):
            per_page = 10

        qs = (
            Download.objects
            .filter(tab=tab_key)
            .select_related('category', 'author')
            .prefetch_related('tags')
            .order_by('-created_at')
        )

        if not can_manage:
            qs = qs.filter(status='published')
            status_filter = ''

        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(category__name__icontains=search) |
                Q(tags__name__icontains=search)
            ).distinct()

        if can_manage and status_filter in ('draft', 'published', 'archived'):
            qs = qs.filter(status=status_filter)

        if cat_filter:
            qs = qs.filter(category_id=cat_filter)

        if tag_filter:
            qs = qs.filter(tags__pk=tag_filter)

        if can_manage:
            total_count     = Download.objects.filter(tab=tab_key).count()
            published_count = Download.objects.filter(tab=tab_key, status='published').count()
            draft_count     = Download.objects.filter(tab=tab_key, status='draft').count()
            archived_count  = Download.objects.filter(tab=tab_key, status='archived').count()
        else:
            total_count     = Download.objects.filter(tab=tab_key, status='published').count()
            published_count = total_count
            draft_count     = None
            archived_count  = None

        paginator = Paginator(qs, per_page)
        page_obj  = paginator.get_page(request.GET.get(f'page_{tab_key}', '').strip() or 1)

        categories = DownloadCategory.objects.filter(tab=tab_key)
        all_tags   = DownloadTag.objects.all()

        return {
            f'{tab_key}_items':           page_obj,
            f'{tab_key}_search':          search,
            f'{tab_key}_status_filter':   status_filter,
            f'{tab_key}_cat_filter':      cat_filter,
            f'{tab_key}_tag_filter':      tag_filter,
            f'{tab_key}_per_page':        per_page,
            f'{tab_key}_total_count':     total_count,
            f'{tab_key}_published_count': published_count,
            f'{tab_key}_draft_count':     draft_count,
            f'{tab_key}_archived_count':  archived_count,
            f'{tab_key}_categories':      categories,
            f'{tab_key}_all_tags':        all_tags,
        }

    ctx = {
        'active_tab': active_tab,
        'can_manage': can_manage,
        'can_view':   can_view,
    }
    ctx.update(_build_tab('forms', request))
    ctx.update(_build_tab('files', request))

    cat_search = request.GET.get('cat_search', '').strip()
    cats_qs    = DownloadCategory.objects.all()
    if cat_search:
        cats_qs = cats_qs.filter(name__icontains=cat_search)

    tag_search = request.GET.get('tag_search', '').strip()
    tags_qs    = DownloadTag.objects.all()
    if tag_search:
        tags_qs = tags_qs.filter(name__icontains=tag_search)

    ctx.update({
        'all_categories': DownloadCategory.objects.all(),
        'all_tags_list':  DownloadTag.objects.all(),
        'cats_qs':        cats_qs,
        'cat_search':     cat_search,
        'tags_qs':        tags_qs,
        'tag_search':     tag_search,
    })

    return render(request, 'downloads.html', ctx)


@login_required
def download_create(request):
    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to create downloads.')
        return redirect('downloads')

    if request.method == 'POST':
        title          = request.POST.get('title', '').strip()
        tab            = request.POST.get('tab_type', 'forms')
        category_pk    = request.POST.get('category', '')
        tags_input     = request.POST.get('tags_input', '').strip()
        status         = request.POST.get('status', 'draft')
        archive_policy = request.POST.get('archive_policy', 'default')
        archive_date   = request.POST.get('archive_date', '') or None
        attachment     = request.FILES.get('attachment')

        if tab not in ('forms', 'files'):
            tab = 'forms'

        errors = []
        if not title:       errors.append('Title is required.')
        if not category_pk: errors.append('Category is required.')
        if not attachment:  errors.append('Attachment is required.')
        if status not in ('draft', 'published'):
            status = 'draft'

        category = None
        if category_pk:
            try:
                category = DownloadCategory.objects.get(pk=category_pk)
            except DownloadCategory.DoesNotExist:
                errors.append('Selected category does not exist.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(f'/downloads/?tab={tab}')

        dl = Download(
            title=title, tab=tab, category=category,
            status=status, archive_policy=archive_policy,
            archive_date=archive_date, author=request.user,
            attachment=attachment,
        )
        dl.save()
        if tags_input:
            dl.tags.set(_resolve_download_tags(tags_input))

        verb = 'published' if status == 'published' else 'saved as draft'
        messages.success(request, f'"{title}" has been {verb}.')

    return redirect(f'/downloads/?tab={tab}')


@login_required
def download_edit(request, pk):
    dl = get_object_or_404(Download, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to edit downloads.')
        return redirect('downloads')

    if request.method == 'POST':
        title            = request.POST.get('title', '').strip()
        category_pk      = request.POST.get('category', '')
        tags_input       = request.POST.get('tags_input', '').strip()
        status           = request.POST.get('status', dl.status)
        archive_policy   = request.POST.get('archive_policy', dl.archive_policy)
        archive_date     = request.POST.get('archive_date', '') or None
        attachment       = request.FILES.get('attachment')
        clear_attachment = request.POST.get('clear_attachment') == '1'

        errors = []
        if not title:       errors.append('Title is required.')
        if not category_pk: errors.append('Category is required.')
        if status not in ('draft', 'published', 'archived'):
            status = dl.status

        category = None
        if category_pk:
            try:
                category = DownloadCategory.objects.get(pk=category_pk)
            except DownloadCategory.DoesNotExist:
                errors.append('Selected category does not exist.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(f'/downloads/?tab={dl.tab}')

        dl.title          = title
        dl.category       = category
        dl.status         = status
        dl.archive_policy = archive_policy
        dl.archive_date   = archive_date

        if clear_attachment and dl.attachment:
            dl.attachment.delete(save=False)
            dl.attachment = None
        elif attachment:
            if dl.attachment:
                dl.attachment.delete(save=False)
            dl.attachment = attachment

        dl.save()
        dl.tags.set(_resolve_download_tags(tags_input))

        messages.success(request, f'"{title}" has been updated.')

    return redirect(f'/downloads/?tab={dl.tab}')


@login_required
def download_delete(request, pk):
    dl = get_object_or_404(Download, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to delete downloads.')
        return redirect('downloads')

    if request.method == 'POST':
        tab   = dl.tab
        title = dl.title
        if dl.attachment:
            dl.attachment.delete(save=False)
        dl.delete()
        messages.success(request, f'"{title}" has been deleted.')
        return redirect(f'/downloads/?tab={tab}')

    return redirect('downloads')


@login_required
def download_toggle_status(request, pk):
    if not _can_manage_downloads(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    dl     = get_object_or_404(Download, pk=pk)
    action = request.POST.get('action', '')

    if action == 'publish':
        dl.status = Download.STATUS_PUBLISHED
    elif action == 'draft':
        dl.status = Download.STATUS_DRAFT
    elif action == 'archive':
        dl.status = Download.STATUS_ARCHIVED
    elif action == 'unarchive':
        dl.status = Download.STATUS_PUBLISHED if dl.published_at else Download.STATUS_DRAFT
    else:
        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    dl.save()
    return JsonResponse({'success': True, 'status': dl.status, 'label': dl.get_status_display()})


# ── Category CRUD ──────────────────────────────────────────────────────────────

@login_required
def download_category_add(request):
    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('downloads')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        tab  = request.POST.get('tab', 'forms')
        if tab not in ('forms', 'files'):
            tab = 'forms'
        if not name:
            messages.error(request, 'Category name is required.')
        elif DownloadCategory.objects.filter(name__iexact=name, tab=tab).exists():
            messages.error(request, f'Category "{name}" already exists for this tab.')
        else:
            DownloadCategory.objects.create(name=name, tab=tab)
            messages.success(request, f'Category "{name}" has been created.')

    return redirect('/downloads/?tab=categories')


@login_required
def download_category_edit(request, pk):
    cat = get_object_or_404(DownloadCategory, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('downloads')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        tab  = request.POST.get('tab', cat.tab)
        if tab not in ('forms', 'files'):
            tab = cat.tab
        if not name:
            messages.error(request, 'Category name is required.')
        elif DownloadCategory.objects.filter(name__iexact=name, tab=tab).exclude(pk=pk).exists():
            messages.error(request, f'Category "{name}" already exists.')
        else:
            cat.name = name
            cat.tab  = tab
            cat.save()
            messages.success(request, f'Category updated to "{name}".')

    return redirect('/downloads/?tab=categories')


@login_required
def download_category_delete(request, pk):
    cat = get_object_or_404(DownloadCategory, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage categories.')
        return redirect('downloads')

    if request.method == 'POST':
        if cat.download_count > 0:
            messages.error(request, f'Cannot delete "{cat.name}" — it has {cat.download_count} item(s) assigned.')
        else:
            name = cat.name
            cat.delete()
            messages.success(request, f'Category "{name}" has been deleted.')

    return redirect('/downloads/?tab=categories')


# ── Tag CRUD ───────────────────────────────────────────────────────────────────

@login_required
def download_tag_add(request):
    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('downloads')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Tag name is required.')
        elif DownloadTag.objects.filter(name__iexact=name).exists():
            messages.error(request, f'Tag "{name}" already exists.')
        else:
            DownloadTag.objects.create(name=name)
            messages.success(request, f'Tag "{name}" has been created.')

    return redirect('/downloads/?tab=tags')


@login_required
def download_tag_edit(request, pk):
    tag = get_object_or_404(DownloadTag, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('downloads')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Tag name is required.')
        elif DownloadTag.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            messages.error(request, f'Tag "{name}" already exists.')
        else:
            tag.name = name
            tag.save()
            messages.success(request, f'Tag updated to "{name}".')

    return redirect('/downloads/?tab=tags')


@login_required
def download_tag_delete(request, pk):
    tag = get_object_or_404(DownloadTag, pk=pk)

    if not _can_manage_downloads(request.user):
        messages.error(request, 'You do not have permission to manage tags.')
        return redirect('downloads')

    if request.method == 'POST':
        name = tag.name
        tag.delete()
        messages.success(request, f'Tag "{name}" has been deleted.')

    return redirect('/downloads/?tab=tags')




@login_required
def messenger(request):
    return render(request, 'messenger.html')

@login_required
def messenger_users(request):
    """List all users, excluding those the current user has blocked OR been blocked by."""
    from .models import UserProfile, BlockedUser
    
    # IDs the current user has blocked
    i_blocked = set(BlockedUser.objects.filter(blocker=request.user).values_list('blocked_id', flat=True))
    # IDs that blocked the current user
    blocked_me = set(BlockedUser.objects.filter(blocked=request.user).values_list('blocker_id', flat=True))
    excluded = i_blocked | blocked_me
 
    profiles = UserProfile.objects.select_related('user').filter(
        user__is_active=True, user__is_superuser=False
    ).exclude(user=request.user).exclude(user__id__in=excluded)
 
    users = [{
        'id':         p.user.pk,
        'username':   p.user.username,
        'name':       p.get_full_name_with_middle(),
        'initials':   p.user.first_name[:1].upper() + p.user.last_name[:1].upper(),
        'avatar':     p.avatar.url if p.avatar else None,
        'position':   p.position,
        'department': p.department,
        'bio':        p.bio,
        'mobile':     p.mobile_number,
        'is_online':  p.is_online,
    } for p in profiles]
    return JsonResponse({'users': users})

@login_required
def messenger_conversations(request):
    """
    Returns conversations for the current user.
    Each conv includes: muted, muted_until, archived, blocked_by_me, blocked_by_them.
    Archived conversations are included but flagged — the frontend filters/separates them.
    """
    from .models import (
        Conversation, Message,
        ConversationMute, ArchivedConversation, BlockedUser,
    )
    from django.utils import timezone
 
    # Build lookup sets for fast membership testing
    mute_map = {
        m.conversation_id: m
        for m in ConversationMute.objects.filter(user=request.user)
        if m.is_active           # auto-expire timed mutes
    }
    # Clean up expired mutes silently
    ConversationMute.objects.filter(
        user=request.user,
        muted_until__lt=timezone.now()
    ).delete()
    # Rebuild after cleanup
    mute_map = {
        m.conversation_id: m
        for m in ConversationMute.objects.filter(user=request.user)
    }
 
    archived_ids = set(
        ArchivedConversation.objects
        .filter(user=request.user)
        .values_list('conversation_id', flat=True)
    )
    i_blocked_ids = set(
        BlockedUser.objects.filter(blocker=request.user).values_list('blocked_id', flat=True)
    )
    blocked_me_ids = set(
        BlockedUser.objects.filter(blocked=request.user).values_list('blocker_id', flat=True)
    )
 
    convs = Conversation.objects.filter(participants=request.user).prefetch_related('participants', 'messages')
    result = []
 
    for c in convs:
        if c.is_group:
            # ── Group conversation ─────────────────────────────────────────
            members = list(c.participants.select_related('profile').all())
            member_list = [{
                'id':       m.pk,
                'name':     m.get_full_name() or m.username,
                'initials': m.first_name[:1].upper() + m.last_name[:1].upper(),
                'avatar':   m.profile.avatar.url if hasattr(m, 'profile') and m.profile.avatar else None,
                'is_online': getattr(getattr(m, 'profile', None), 'is_online', False),
            } for m in members]

            last_msg   = c.messages.last()
            unread     = c.messages.filter(is_read=False).exclude(sender=request.user).count()
            mute_obj   = mute_map.get(c.pk)
            is_muted   = mute_obj is not None
            is_archived = c.pk in archived_ids

            last_preview = ''
            if last_msg:
                if last_msg.is_system:
                    last_preview = last_msg.body[:60] if last_msg.body else ''
                elif last_msg.sender:
                    sender_first = last_msg.sender.first_name or last_msg.sender.username
                    last_preview = f'{sender_first}: {last_msg.body[:50]}' if last_msg.body else f'{sender_first}: Attachment'

            result.append({
                'id': c.pk,
                'is_group':    True,
                'name':        c.name or 'Group Chat',
                'initials':    c.get_initials(),
                'avatar':      c.avatar.url if c.avatar else None,
                'created_by':  c.created_by_id,
                'members':     member_list,
                'recipient':   None,      # null for groups — frontend checks is_group
                'last_message':      last_preview,
                'last_message_time': last_msg.created_at.isoformat() if last_msg else None,
                'unread_count':      unread,
                'is_muted':          is_muted,
                'muted_until':       mute_obj.muted_until.isoformat() if (mute_obj and mute_obj.muted_until) else None,
                'is_archived':       is_archived,
                'blocked_by_me':     False,
                'blocked_by_them':   False,
            })
        else:
            # ── DM conversation ────────────────────────────────────────────
            other = c.participants.exclude(pk=request.user.pk).first()
            if not other:
                continue

            profile  = getattr(other, 'profile', None)
            last_msg = c.messages.last()
            unread   = c.messages.filter(is_read=False).exclude(sender=request.user).count()

            last_preview = last_msg.body[:60] if last_msg and last_msg.body else ''
            if not last_preview and last_msg and last_msg.attachment:
                last_preview = 'Sent an attachment'

            mute_obj        = mute_map.get(c.pk)
            is_muted        = mute_obj is not None
            muted_until     = mute_obj.muted_until.isoformat() if (mute_obj and mute_obj.muted_until) else None
            is_archived     = c.pk in archived_ids
            blocked_by_me   = other.pk in i_blocked_ids
            blocked_by_them = other.pk in blocked_me_ids

            result.append({
                'id': c.pk,
                'is_group':    False,
                'recipient': {
                    'id':         other.pk,
                    'username':   other.username,
                    'name':       other.get_full_name() or other.username,
                    'initials':   other.first_name[:1].upper() + other.last_name[:1].upper(),
                    'avatar':     profile.avatar.url if profile and profile.avatar else None,
                    'position':   profile.position if profile else '',
                    'department': profile.department if profile else '',
                    'bio':        profile.bio if profile else '',
                    'mobile':     profile.mobile_number if profile else '',
                    'is_online':  getattr(profile, 'is_online', False),
                },
                'last_message':      last_preview,
                'last_message_time': last_msg.created_at.isoformat() if last_msg else None,
                'unread_count':      unread,
                'is_muted':          is_muted,
                'muted_until':       muted_until,
                'is_archived':       is_archived,
                'blocked_by_me':     blocked_by_me,
                'blocked_by_them':   blocked_by_them,
            })

    return JsonResponse({'conversations': result})

@login_required
def messenger_messages(request, conv_id):
    from .models import Conversation, Message
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
    msgs = conv.messages.select_related('sender', 'reply_to', 'reply_to__sender').order_by('created_at').exclude(unsent_for=request.user)
    return JsonResponse({'messages': [{
        'id':              m.pk,
        'body':            m.body,
        'sender_id':       m.sender.pk if m.sender else None,
        'created_at':      m.created_at.isoformat(),
        'attachment_url':  m.attachment.url if m.attachment else None,
        'attachment_name': m.attachment_name,
        'is_image':        m.is_image,
        'is_system':       m.is_system,
        'is_unsent':       m.is_unsent,
        'status':          m.status,
        'reply_to': {
            'id':              m.reply_to.pk,
            'body':            m.reply_to.body,
            'is_image':        m.reply_to.is_image,
            'attachment_name': m.reply_to.attachment_name,
            'sender_name': (
                m.reply_to.sender.get_full_name() or m.reply_to.sender.username
                if m.reply_to.sender else 'System'
            ),
        } if m.reply_to_id else None,
    } for m in msgs]})

@login_required
def messenger_send(request, conv_id):
    """Send a message — blocked parties cannot send."""
    if request.method == 'POST':
        from .models import Conversation, Message, BlockedUser
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
 
        conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
        recipient = conv.participants.exclude(pk=request.user.pk).first()
 
        # ── Block check: sender blocked by recipient, or sender blocked recipient ──
        if not conv.is_group and recipient:
            is_blocked = BlockedUser.objects.filter(
                blocker=recipient, blocked=request.user
            ).exists() or BlockedUser.objects.filter(
                blocker=request.user, blocked=recipient
            ).exists()
            if is_blocked:
                return JsonResponse({'success': False, 'error': 'blocked'}, status=403)
 
        body       = request.POST.get('body', '').strip()
        attachment = request.FILES.get('attachment')
        reply_to_id = request.POST.get('reply_to_id')
 
        if not body and not attachment:
            return JsonResponse({'success': False, 'error': 'Empty message'}, status=400)
 
        msg = Message.objects.create(
            conversation=conv,
            sender=request.user,
            body=body,
            attachment=attachment,
            attachment_name=attachment.name if attachment else '',
            reply_to_id=reply_to_id or None,
        )
 
        conv.updated_at = msg.created_at
        conv.save()
 
        channel_layer = get_channel_layer()
 
        from .models import ConversationMute
        from django.utils import timezone

        sender_profile   = request.user.profile
        sender_avatar    = sender_profile.avatar.url if sender_profile.avatar else ''
        first = request.user.first_name[:1].upper()
        last  = request.user.last_name[:1].upper()

        recipients_to_notify = (
            conv.participants.exclude(pk=request.user.pk)
            if conv.is_group
            else ([recipient] if recipient else [])
        )

        for r in recipients_to_notify:
            mute = ConversationMute.objects.filter(user=r, conversation=conv).first()
            should_notify = not mute or (mute.muted_until and timezone.now() > mute.muted_until)

            if should_notify:
                unread_count = Message.objects.filter(
                    conversation__participants=r,
                    is_read=False,
                ).exclude(sender=r).count()

                async_to_sync(channel_layer.group_send)(
                    f'notif_user_{r.pk}',
                    {
                        'type':            'new_chat_message',
                        'conv_id':         conv.pk,
                        'sender_id':       request.user.pk,
                        'sender_name':     request.user.get_full_name() or request.user.username,
                        'sender_avatar':   sender_avatar,
                        'sender_initials': first + last,
                        'body':            msg.body or 'Sent an attachment',
                        'created_at':      msg.created_at.isoformat(),
                        'unread_count':    unread_count,
                    }
                )
 
        msg_data = {
            'id':              msg.pk,
            'body':            msg.body,
            'sender_id':       request.user.pk,
            'created_at':      msg.created_at.isoformat(),
            'attachment_url':  msg.attachment.url if msg.attachment else None,
            'attachment_name': msg.attachment_name,
            'is_image':        msg.is_image,
            'status':          msg.status,
            'reply_to': {
                'id':          msg.reply_to.pk,
                'body':        msg.reply_to.body,
                'is_image':    msg.reply_to.is_image,
                'attachment_name': msg.reply_to.attachment_name,
                'sender_name': (
                    msg.reply_to.sender.get_full_name() or msg.reply_to.sender.username
                ),
            } if msg.reply_to_id else None,
        }
 
        async_to_sync(channel_layer.group_send)(
            f'chat_{conv_id}',
            {'type': 'chat_message', 'message': msg_data}
        )
 
        return JsonResponse({'success': True, 'message': msg_data})
    return JsonResponse({'success': False}, status=405)

@login_required
def messenger_read(request, conv_id):
    if request.method == 'POST':
        from .models import Conversation, Message
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)

        # Get IDs of messages being marked seen (sent by the OTHER person)
        newly_seen = list(
            conv.messages
            .filter(is_read=False)
            .exclude(sender=request.user)
            .values_list('pk', flat=True)
        )

        conv.messages.filter(is_read=False).exclude(sender=request.user).update(
            is_read=True, status=Message.STATUS_SEEN
        )

        # Notify the original sender that their messages were seen
        if newly_seen:
            other = conv.participants.exclude(pk=request.user.pk).first()
            if other:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'chat_{conv_id}',
                    {
                        'type':       'messages_seen',
                        'message_ids': newly_seen,
                        'seen_by':    request.user.pk,
                    }
                )

        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)

@login_required
def messenger_delete_conversation(request, conv_id):
    if request.method == 'POST':
        from .models import Conversation
        conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
        conv.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)

@login_required
def messenger_start(request):
    if request.method == 'POST':
        import json as _json
        from .models import Conversation
        data    = _json.loads(request.body)
        other   = get_object_or_404(User, pk=data['user_id'])
        # Find existing or create new
        existing = Conversation.objects.filter(
            participants=request.user, is_group=False
        ).filter(participants=other).first()
        if existing:
            return JsonResponse({'conversation_id': existing.pk})
        conv = Conversation.objects.create()
        conv.participants.add(request.user, other)
        return JsonResponse({'conversation_id': conv.pk})
    return JsonResponse({'success': False}, status=405)

@login_required
def messenger_create_group(request):
    """POST: Create a group conversation."""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    import json as _json
    from .models import Conversation

    name        = request.POST.get('name', '').strip()
    member_ids  = request.POST.getlist('member_ids')  # list of user PKs
    avatar      = request.FILES.get('avatar')

    if not name:
        return JsonResponse({'success': False, 'error': 'Group name is required.'}, status=400)
    if len(member_ids) < 2:
        return JsonResponse({'success': False, 'error': 'Select at least 2 members.'}, status=400)

    conv = Conversation.objects.create(
        is_group=True,
        name=name,
        created_by=request.user,
    )
    if avatar:
        conv.avatar = avatar
        conv.save()

    # Add creator + selected members
    members = list(User.objects.filter(pk__in=member_ids, is_active=True))
    conv.participants.add(request.user, *members)

    return JsonResponse({'success': True, 'conversation_id': conv.pk})


@login_required
def messenger_group_add_members(request, conv_id):
    from .models import Conversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user, is_group=True)

    member_ids  = request.POST.getlist('member_ids')
    new_members = list(User.objects.filter(pk__in=member_ids, is_active=True))
    conv.participants.add(*new_members)

    # System message
    adder_name = request.user.get_full_name() or request.user.username
    for member in new_members:
        member_name = member.get_full_name() or member.username
        _send_group_system_message(conv, f'{adder_name} added {member_name} to the group.')

    return JsonResponse({'success': True})


@login_required
def messenger_group_remove_member(request, conv_id):
    import json as _json
    from .models import Conversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user, is_group=True)

    data      = _json.loads(request.body or '{}')
    target_id = data.get('member_id') or data.get('user_id')
    target    = get_object_or_404(User, pk=target_id)

    if target != request.user and conv.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    conv.participants.remove(target)

    target_name = target.get_full_name() or target.username
    _send_group_system_message(conv, f'{target_name} was removed from the group.')

    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'notif_user_{target.pk}',
        {
            'type':           'kicked_from_group',
            'conv_id':        conv.pk,
            'conv_name':      conv.name or 'Group Chat',
            'kicked_user_id': target.pk,
        }
    )

    return JsonResponse({'success': True})

@login_required
def messenger_leave_group(request, conv_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import Conversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
    conv.participants.remove(request.user)

    # System message
    full_name = request.user.get_full_name() or request.user.username
    _send_group_system_message(conv, f'{full_name} left the group.')

    return JsonResponse({'success': True})


@login_required
def messenger_group_update(request, conv_id):
    """POST: Update group name/avatar."""
    from .models import Conversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user, is_group=True)

    if conv.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Only the creator can edit this group.'}, status=403)

    name   = request.POST.get('name', '').strip()
    avatar = request.FILES.get('avatar')

    if name:
        conv.name = name
    if avatar:
        if conv.avatar:
            conv.avatar.delete(save=False)
        conv.avatar = avatar
    conv.save()

    return JsonResponse({'success': True})



import json as _json
from django.utils import timezone as _tz
import datetime as _dt


# ── helpers ────────────────────────────────────────────────────────────────────

def _mute_duration_to_dt(duration_str):
    """Convert a duration key to a concrete datetime (or None for indefinite)."""
    map_ = {
        'indefinite': None,
        '1h':  _dt.timedelta(hours=1),
        '8h':  _dt.timedelta(hours=8),
        '24h': _dt.timedelta(hours=24),
        '1w':  _dt.timedelta(weeks=1),
    }
    delta = map_.get(duration_str)
    if delta is None:
        return None          # indefinite
    return _tz.now() + delta


# ── MUTE ──────────────────────────────────────────────────────────────────────

@login_required
def messenger_mute(request, conv_id):
    """POST {duration: '1h'|'8h'|'24h'|'1w'|'indefinite'} → mute conversation."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import Conversation, ConversationMute
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)

    data     = _json.loads(request.body or '{}')
    duration = data.get('duration', 'indefinite')
    until    = _mute_duration_to_dt(duration)

    mute, _ = ConversationMute.objects.get_or_create(
        user=request.user, conversation=conv,
        defaults={'muted_until': until},
    )
    mute.muted_until = until
    mute.save()

    return JsonResponse({'success': True, 'muted_until': until.isoformat() if until else None})


@login_required
def messenger_unmute(request, conv_id):
    """POST → unmute conversation."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import Conversation, ConversationMute
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
    ConversationMute.objects.filter(user=request.user, conversation=conv).delete()

    return JsonResponse({'success': True})


# ── ARCHIVE ───────────────────────────────────────────────────────────────────

@login_required
def messenger_archive(request, conv_id):
    """POST → archive conversation."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import Conversation, ArchivedConversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
    ArchivedConversation.objects.get_or_create(user=request.user, conversation=conv)

    return JsonResponse({'success': True})


@login_required
def messenger_unarchive(request, conv_id):
    """POST → unarchive conversation."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import Conversation, ArchivedConversation
    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)
    ArchivedConversation.objects.filter(user=request.user, conversation=conv).delete()

    return JsonResponse({'success': True})


# ── BLOCK ─────────────────────────────────────────────────────────────────────

@login_required
def messenger_block(request, user_id):
    """POST → block a user."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import BlockedUser
    target = get_object_or_404(User, pk=user_id)
    if target == request.user:
        return JsonResponse({'success': False, 'error': 'Cannot block yourself.'})

    BlockedUser.objects.get_or_create(blocker=request.user, blocked=target)
    return JsonResponse({'success': True})


@login_required
def messenger_unblock(request, user_id):
    """POST → unblock a user."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from .models import BlockedUser
    target = get_object_or_404(User, pk=user_id)
    BlockedUser.objects.filter(blocker=request.user, blocked=target).delete()
    return JsonResponse({'success': True})


@login_required
def messenger_unsend(request, conv_id, msg_id):
    """POST {scope: 'everyone'|'you'} → unsend a message."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    import json as _json
    from .models import Conversation, Message
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    conv = get_object_or_404(Conversation, pk=conv_id, participants=request.user)

    data  = _json.loads(request.body or '{}')
    scope = data.get('scope', 'everyone')

    if scope == 'everyone':
        # Only the sender can unsend for everyone
        try:
            msg = Message.objects.get(pk=msg_id, conversation=conv, sender=request.user)
        except Message.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Message not found.'}, status=404)

        msg.is_unsent = True
        msg.body = ''
        if msg.attachment:
            msg.attachment.delete(save=False)
            msg.attachment = None
            msg.attachment_name = ''
        msg.save()

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'chat_{conv_id}',
            {
                'type':       'message_unsent',
                'message_id': msg.pk,
                'sender_id':  request.user.pk,
            }
        )
    else:
        # "remove for you" — any participant can hide any message from their own view
        try:
            msg = Message.objects.get(pk=msg_id, conversation=conv)
        except Message.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Message not found.'}, status=404)

        msg.unsent_for.add(request.user)

    return JsonResponse({'success': True, 'scope': scope})


def _can_manage_pgs(user):
    """Org-wide PGS management access (any department, create/archive/delete deliverables)."""
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return hasattr(user, 'profile') and user.profile.can_edit_module('pgs')


def _can_submit_for_department(user, department):
    """
    A user may log/edit/archive a deliverable or progress entry for their
    own department, or for any department if they hold org-wide PGS
    management access. This is the single choke point that keeps users
    out of other departments' deliverables — every add/edit/archive/delete
    view below must route its permission check through this function.
    """
    if _can_manage_pgs(user):
        return True
    return hasattr(user, 'profile') and user.profile.department == department


def _actor_display_name(user):
    return user.get_full_name() or user.username


def _notify_pgs_event(actor, notif_type, title, message, url):
    """
    Broadcast a PGS notification to every other active user, so anything
    logged/added/changed in PGS shows up in everyone's notification bell.
    These are created as plain DB rows — picked up by the existing
    notifications_list polling — since PGS doesn't have a live websocket
    channel the way Messenger does. If you want a live push too, this is
    the spot to also channel_layer.group_send to notif_user_{r.pk}, same
    pattern as messenger_send.
    """
    from .models import Notification
    recipients = User.objects.filter(is_active=True).exclude(pk=actor.pk)
    Notification.objects.bulk_create([
        Notification(
            recipient=r, actor=actor, notif_type=notif_type,
            title=title, message=message, url=url,
        )
        for r in recipients
    ])


@login_required
def pgs_dashboard(request):
    from .models import PGSIndicator, DEPARTMENT_CHOICES, get_grouped_department_choices
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    from django.db.models import Q
    import json as _json

    can_manage    = _can_manage_pgs(request.user)
    my_department = request.user.profile.department if hasattr(request.user, 'profile') else ''
    my_department_label = dict(DEPARTMENT_CHOICES).get(my_department, my_department)

    selected_department = request.GET.get('department', '').strip()
    show_archived        = request.GET.get('show_archived') == '1'
    show_overdue         = request.GET.get('overdue') == '1'
    search_query         = request.GET.get('q', '').strip()

    PER_PAGE_CHOICES = [10, 25, 50, 100]
    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    if per_page not in PER_PAGE_CHOICES:
        per_page = 10

    indicators_qs = (
        PGSIndicator.objects
        .select_related('created_by')
        .prefetch_related('entries', 'entries__submitted_by')
        .order_by('department', 'title')
    )
    if not show_archived:
        indicators_qs = indicators_qs.filter(is_archived=False)
    if selected_department:
        indicators_qs = indicators_qs.filter(department=selected_department)
    if search_query:
        indicators_qs = indicators_qs.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )

    indicators = list(indicators_qs)
    for ind in indicators:
        latest = ind.latest_entry
        ind.latest = latest
        ind.pct = latest.percent_of_target if latest else None
        ind.status_label = latest.status if latest else 'none'
        # Department-scoped edit permission — same rule used server-side by
        # every mutating view, so what the user sees matches what they can do.
        ind.can_edit = _can_submit_for_department(request.user, ind.department)
        ind.history = list(ind.entries.all())

    # "Past due" quick filter, driven by the clickable stat card. Applied in
    # Python (not the queryset) since is_overdue depends on is_complete,
    # which itself depends on the latest progress entry — a computed
    # property, not a raw DB column.
    if show_overdue:
        indicators = [ind for ind in indicators if ind.is_overdue]

    # ── Department status mix (for the stacked comparison chart) — computed
    #    across ALL non-archived deliverables for every department that
    #    actually has deliverables, regardless of the department filter.
    #    We tally the org-wide past-due total (used by the "Past due" stat
    #    card, which always stays org-wide), and also build a per-department
    #    pie breakdown (`pie_counts_by_dept`) in the same pass, so the three
    #    charts can be re-scoped to a single department below without a
    #    second query. ──
    dept_summary = {}
    total_past_due = 0
    # Mutually-exclusive 4-way bucket per department, used to slice the pie
    # chart down to one department when `selected_department` is set.
    pie_counts_by_dept = {}
    for label, name in DEPARTMENT_CHOICES:
        dept_indicators = list(
            PGSIndicator.objects.filter(department=label, is_archived=False)
            .prefetch_related('entries')
        )
        if not dept_indicators:
            continue
        # Three buckets: 'on' = Accomplished, 'risk' = Ongoing, 'none' = Not Started
        counts = {'on': 0, 'risk': 0, 'none': 0}
        dept_pie = {'on': 0, 'ongoing': 0, 'not_started': 0, 'past_due': 0}
        pcts = []
        for ind in dept_indicators:
            latest = ind.latest_entry
            if latest:
                counts[latest.status] += 1
                pcts.append(latest.percent_of_target)
            else:
                counts['none'] += 1

            if ind.is_overdue:
                total_past_due += 1
                dept_pie['past_due'] += 1
            elif latest and latest.status == 'on':
                dept_pie['on'] += 1
            elif latest:
                dept_pie['ongoing'] += 1
            else:
                dept_pie['not_started'] += 1

        dept_summary[label] = {
            'name':   name,
            'counts': counts,
            'avg':    round(sum(pcts) / len(pcts)) if pcts else 0,
            'total':  len(dept_indicators),
        }
        pie_counts_by_dept[label] = dept_pie

    overall_avg = (
        round(sum(d['avg'] for d in dept_summary.values() if d['avg']) /
              max(1, len([d for d in dept_summary.values() if d['avg']])))
        if dept_summary else 0
    )

    # ── Scope the three chart datasets to `selected_department`, if any.
    #    The stat cards above (overall_avg, total_past_due) intentionally
    #    stay org-wide — only the charts follow the filter, reusing the
    #    exact same Chart.js instances on the frontend instead of adding
    #    new ones. Clearing the department filter (chart_scope_label=None)
    #    goes back to the org-wide view automatically. ──
    chart_scope_label = dict(DEPARTMENT_CHOICES).get(selected_department) if selected_department else None

    if selected_department and selected_department in dept_summary:
        chart_dept_summary = {selected_department: dept_summary[selected_department]}
        pie_counts = pie_counts_by_dept[selected_department]
    elif selected_department:
        # Selected department has no deliverables at all — empty charts.
        chart_dept_summary = {}
        pie_counts = {'on': 0, 'ongoing': 0, 'not_started': 0, 'past_due': 0}
    else:
        chart_dept_summary = dept_summary
        pie_counts = {
            k: sum(d[k] for d in pie_counts_by_dept.values())
            for k in ('on', 'ongoing', 'not_started', 'past_due')
        }

    dept_names   = [d['name'] for d in chart_dept_summary.values()]
    dept_on      = [d['counts']['on']   for d in chart_dept_summary.values()]
    dept_risk    = [d['counts']['risk'] for d in chart_dept_summary.values()]
    dept_none    = [d['counts']['none'] for d in chart_dept_summary.values()]

    departments_reporting = len(dept_summary)

    # ── Trend by month (average % across all entries submitted that month),
    #    scoped to `selected_department` the same way as the other charts.
    #    No typed "period" needed, we use submitted_at. ──
    month_map = defaultdict(list)
    trend_qs = PGSIndicator.objects.filter(is_archived=False)
    if selected_department:
        trend_qs = trend_qs.filter(department=selected_department)
    for ind in trend_qs.prefetch_related('entries'):
        for e in ind.entries.all():
            key = e.submitted_at.strftime('%Y-%m')
            month_map[key].append(e.percent_of_target)
    month_keys = sorted(month_map.keys())
    trend_labels = [datetime.datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in month_keys]
    trend_values = [round(sum(month_map[m]) / len(month_map[m])) for m in month_keys]

    # ── Pagination ──
    paginator = Paginator(indicators, per_page)
    try:
        page_obj = paginator.page(request.GET.get('page', 1))
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages) if paginator.num_pages else paginator.page(1)

    # Current filters minus "page", reused by pagination links so Prev/Next
    # don't drop the active department/search/overdue/per_page filters.
    qd = request.GET.copy()
    qd.pop('page', None)
    base_querystring = qd.urlencode()

    return render(request, 'pgs_dashboard.html', {
        'indicators':             page_obj.object_list,
        'page_obj':               page_obj,
        'paginator':              paginator,
        'base_querystring':       base_querystring,
        'per_page':               per_page,
        'per_page_choices':       PER_PAGE_CHOICES,
        'search_query':           search_query,
        'show_overdue':           show_overdue,
        'total_past_due':         total_past_due,
        'department_choices':     DEPARTMENT_CHOICES,
        'department_groups':      get_grouped_department_choices(),
        'dept_summary':           dept_summary,
        'dept_names_json':        _json.dumps(dept_names),
        'dept_on_json':           _json.dumps(dept_on),
        'dept_risk_json':         _json.dumps(dept_risk),
        'dept_none_json':         _json.dumps(dept_none),
        'pie_labels_json':        _json.dumps(['Accomplished', 'Ongoing', 'Not Started', 'Past Due']),
        'pie_values_json':        _json.dumps([
            pie_counts['on'], pie_counts['ongoing'],
            pie_counts['not_started'], pie_counts['past_due'],
        ]),
        'trend_labels_json':      _json.dumps(trend_labels),
        'trend_values_json':      _json.dumps(trend_values),
        'overall_avg':            overall_avg,
        'departments_reporting':  departments_reporting,
        'can_manage':             can_manage,
        'my_department':          my_department,
        'my_department_label':    my_department_label,
        'selected_department':    selected_department,
        'show_archived':          show_archived,
        'total_indicators':       PGSIndicator.objects.filter(is_archived=False).count(),
        # NEW — drives chart subtitles + the "Your office" / department
        # filter state; also embedded in the hidden #pgsChartDataJson blob
        # that the frontend re-parses after every AJAX filter reload.
        'chart_scope_label':      chart_scope_label,
        'chart_scope_label_json': _json.dumps(chart_scope_label),
    })


@login_required
def pgs_indicator_add(request):
    from .models import PGSIndicator

    if request.method == 'POST':
        department  = request.POST.get('department', '').strip()
        title       = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        due_date    = request.POST.get('due_date', '').strip() or None

        if not _can_submit_for_department(request.user, department):
            messages.error(request, 'You can only add deliverables for your own department.')
            return redirect('pgs_dashboard')

        errors = []
        if not department: errors.append('Department is required.')
        if not title:      errors.append('Deliverable title is required.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('pgs_dashboard')

        indicator = PGSIndicator.objects.create(
            department=department, title=title, description=description,
            due_date=due_date, created_by=request.user,
        )
        messages.success(request, f'Deliverable "{indicator.title}" has been added.')

        _notify_pgs_event(
            request.user,
            'pgs_deliverable_added',
            'New PGS deliverable added',
            f'{_actor_display_name(request.user)} added "{indicator.title}" under {indicator.get_department_display()}.',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


@login_required
def pgs_indicator_edit(request, pk):
    """
    Edit an existing deliverable's title/description/due date. The
    department itself may only be reassigned by org-wide PGS managers;
    a department-scoped editor cannot move a deliverable to another
    department and cannot edit deliverables that already belong to a
    department other than their own.
    """
    from .models import PGSIndicator
    indicator = get_object_or_404(PGSIndicator, pk=pk)

    # Blocks editing of another department's deliverable outright.
    if not _can_submit_for_department(request.user, indicator.department):
        messages.error(request, 'You can only edit deliverables for your own department.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        due_date    = request.POST.get('due_date', '').strip() or None
        new_department = request.POST.get('department', '').strip()

        errors = []
        if not title:
            errors.append('Deliverable title is required.')

        # Only an org-wide manager may move a deliverable to a different
        # department; otherwise the submitted department value is ignored.
        if new_department and new_department != indicator.department:
            if not _can_manage_pgs(request.user):
                errors.append('You do not have permission to reassign this deliverable to another department.')
            else:
                indicator.department = new_department

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect('pgs_dashboard')

        indicator.title = title
        indicator.description = description
        indicator.due_date = due_date
        indicator.save()
        messages.success(request, f'Deliverable "{indicator.title}" has been updated.')

        _notify_pgs_event(
            request.user,
            'pgs_deliverable_updated',
            'PGS deliverable updated',
            f'{_actor_display_name(request.user)} updated "{indicator.title}".',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


@login_required
def pgs_indicator_archive(request, pk):
    from .models import PGSIndicator
    indicator = get_object_or_404(PGSIndicator, pk=pk)

    if not _can_submit_for_department(request.user, indicator.department):
        messages.error(request, 'You do not have permission to archive this deliverable.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        indicator.is_archived = not indicator.is_archived
        indicator.save()
        verb = 'archived' if indicator.is_archived else 'restored'
        messages.success(request, f'Deliverable "{indicator.title}" has been {verb}.')

        _notify_pgs_event(
            request.user,
            'pgs_deliverable_archived' if indicator.is_archived else 'pgs_deliverable_restored',
            f'PGS deliverable {verb}',
            f'{_actor_display_name(request.user)} {verb} "{indicator.title}".',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


@login_required
def pgs_indicator_delete(request, pk):
    from .models import PGSIndicator
    indicator = get_object_or_404(PGSIndicator, pk=pk)

    if not _can_manage_pgs(request.user):
        messages.error(request, 'You do not have permission to delete deliverables.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        title = indicator.title
        for entry in indicator.entries.all():
            if entry.attachment:
                entry.attachment.delete(save=False)
        indicator.delete()
        messages.success(request, f'Deliverable "{title}" and its progress history have been deleted.')

        _notify_pgs_event(
            request.user,
            'pgs_deliverable_deleted',
            'PGS deliverable deleted',
            f'{_actor_display_name(request.user)} deleted "{title}" and its progress history.',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


def _validate_percent(raw):
    """Shared 0-100% validation used by both add and edit progress entries."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, 'Percent complete must be a number.'
    if value < 0 or value > 100:
        return None, 'Percent complete must be between 0 and 100.'
    return value, None


@login_required
def pgs_entry_add(request, indicator_id):
    from .models import PGSIndicator, PGSProgressEntry
    indicator = get_object_or_404(PGSIndicator, pk=indicator_id)

    if not _can_submit_for_department(request.user, indicator.department):
        messages.error(request, 'You can only submit progress for your own department.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        remarks    = request.POST.get('remarks', '').strip()
        attachment = request.FILES.get('attachment')

        percent_complete, err = _validate_percent(request.POST.get('percent_complete', '').strip())
        if err:
            messages.error(request, err)
            return redirect('pgs_dashboard')

        PGSProgressEntry.objects.create(
            indicator=indicator, percent_complete=percent_complete,
            remarks=remarks, attachment=attachment, submitted_by=request.user,
        )
        messages.success(request, f'Progress for "{indicator.title}" has been recorded.')

        _notify_pgs_event(
            request.user,
            'pgs_progress_logged',
            f'Progress logged: {indicator.title}',
            f'{_actor_display_name(request.user)} logged {round(percent_complete)}% progress on "{indicator.title}".',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


@login_required
def pgs_entry_edit(request, pk):
    """
    Edit an existing progress entry (percent complete, remarks, and
    optionally replace the attached file). Restricted to the entry's own
    department, same as adding/deleting an entry.
    """
    from .models import PGSProgressEntry
    entry = get_object_or_404(PGSProgressEntry, pk=pk)

    if not _can_submit_for_department(request.user, entry.indicator.department):
        messages.error(request, 'You can only edit progress entries for your own department.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        remarks    = request.POST.get('remarks', '').strip()
        attachment = request.FILES.get('attachment')

        percent_complete, err = _validate_percent(request.POST.get('percent_complete', '').strip())
        if err:
            messages.error(request, err)
            return redirect('pgs_dashboard')

        entry.percent_complete = percent_complete
        entry.remarks = remarks
        entry.updated_by = request.user
        if attachment:
            if entry.attachment:
                entry.attachment.delete(save=False)
            entry.attachment = attachment
        entry.save()
        messages.success(request, f'Progress entry for "{entry.indicator.title}" has been updated.')

        _notify_pgs_event(
            request.user,
            'pgs_progress_updated',
            f'Progress updated: {entry.indicator.title}',
            f'{_actor_display_name(request.user)} updated a progress entry on "{entry.indicator.title}".',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')


@login_required
def pgs_entry_delete(request, pk):
    from .models import PGSProgressEntry
    entry = get_object_or_404(PGSProgressEntry, pk=pk)

    if not _can_submit_for_department(request.user, entry.indicator.department):
        messages.error(request, 'You do not have permission to delete this entry.')
        return redirect('pgs_dashboard')

    if request.method == 'POST':
        if entry.attachment:
            entry.attachment.delete(save=False)
        title = entry.indicator.title
        when = entry.period_display
        entry.delete()
        messages.success(request, f'Progress entry for "{title}" ({when}) has been removed.')

        _notify_pgs_event(
            request.user,
            'pgs_progress_deleted',
            f'Progress entry removed: {title}',
            f'{_actor_display_name(request.user)} removed a progress entry ({when}) from "{title}".',
            reverse('pgs_dashboard'),
        )

    return redirect('pgs_dashboard')

def _notify_pgs_event(actor, notif_type, title, message, url):
    """
    Broadcast a PGS notification to every other active user: creates the DB
    rows (picked up by notifications_list polling / on next page load), and
    also pushes each one live over the notif_user_{pk} websocket group —
    same pattern ChatConsumer/messenger uses for chat_message — so the bell
    updates immediately instead of waiting for a poll.
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from django.db.models import Count
    from .models import Notification

    recipients = User.objects.filter(is_active=True).exclude(pk=actor.pk)
    if not recipients.exists():
        return

    notifications = Notification.objects.bulk_create([
        Notification(
            recipient=r, actor=actor, notif_type=notif_type,
            title=title, message=message, url=url,
        )
        for r in recipients
    ])

    # Unread count per recipient, fetched in a single query rather than one
    # per user, so a large org-wide broadcast doesn't trigger N+1 queries.
    recipient_ids = [n.recipient_id for n in notifications]
    unread_counts = dict(
        Notification.objects.filter(recipient_id__in=recipient_ids, is_read=False)
        .values('recipient_id')
        .annotate(count=Count('id'))
        .values_list('recipient_id', 'count')
    )

    channel_layer = get_channel_layer()
    actor_name = _actor_display_name(actor)

    for n in notifications:
        async_to_sync(channel_layer.group_send)(
            f'notif_user_{n.recipient_id}',
            {
                'type':         'send_notification',   # -> NotificationConsumer.send_notification
                'id':           n.pk,
                'notif_type':   n.notif_type,
                'title':        n.title,
                'message':      n.message,
                'url':          n.url,
                'actor':        actor_name,
                'created_at':   n.created_at.strftime('%b %d, %Y %I:%M %p'),
                'unread_count': unread_counts.get(n.recipient_id, 0),
            }
        )