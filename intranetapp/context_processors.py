from .models import Role


class RoleModulePerms:
    """
    Wraps a Role instance and exposes has_access() as attribute access.
    e.g. user_perms.wiki  →  role.has_access('wiki')
    Administrator role returns True for all modules automatically.
    """
    def __init__(self, role):
        self._role = role

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if self._role is None:
            return False
        return self._role.has_access(name)


def user_permissions(request):
    """
    Makes 'user_perms' available in all templates.
    Usage in templates:  {% if user_perms.wiki %} ... {% endif %}
    """
    if not request.user.is_authenticated:
        return {'user_perms': None}

    try:
        profile = request.user.profile
    except AttributeError:
        return {'user_perms': None}

    return {'user_perms': RoleModulePerms(profile.role)}