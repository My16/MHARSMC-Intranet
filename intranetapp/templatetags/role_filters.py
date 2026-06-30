from django import template
from intranetapp.models import DEPARTMENT_CHOICES

register = template.Library()

_DEPT_LABELS = dict(DEPARTMENT_CHOICES)

@register.filter(name='has_access')
def has_access(role, module_key):
    """
    Usage in template:  {{ role|has_access:"wiki" }}
    Returns True if the role grants access to the given module_key.
    """
    if role is None:
        return False
    return role.has_access(module_key)


@register.filter
def perm_level(role, module_key):
    """
    Returns 'none', 'view', or 'edit' for a given module key.
    Administrator roles always return 'edit' regardless of field values.
    """
    if role is None:
        return 'none'
    if role.is_administrator:
        return 'edit'
    return getattr(role, module_key, 'none')

@register.filter
def has_module_access(user, module_key):
    """Usage: {{ request.user|has_module_access:'press_releases' }}"""
    if user.is_superuser:
        return True
    if not hasattr(user, 'profile'):
        return False
    return user.profile.has_module_access(module_key)


@register.filter(name='file_icon')
def file_icon(filename):
    """Return a Font Awesome icon class name for a filename's extension.

    Usage: {{ attachment.original_name|file_icon }} -> 'fa-file-pdf'
    The template typically renders: <i class="fa-solid {{ att.original_name|file_icon }}"></i>
    """
    import os
    if not filename:
        return 'fa-file'
    _, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip('.')
    mapping = {
        'pdf': 'fa-file-pdf',
        'doc': 'fa-file-word', 'docx': 'fa-file-word',
        'xls': 'fa-file-excel', 'xlsx': 'fa-file-excel',
        'csv': 'fa-file-csv',
        'ppt': 'fa-file-powerpoint', 'pptx': 'fa-file-powerpoint',
        'zip': 'fa-file-zipper', 'rar': 'fa-file-zipper', '7z': 'fa-file-zipper',
        'png': 'fa-file-image', 'jpg': 'fa-file-image', 'jpeg': 'fa-file-image', 'gif': 'fa-file-image',
        'mp4': 'fa-file-video', 'mov': 'fa-file-video', 'mkv': 'fa-file-video',
        'mp3': 'fa-file-audio', 'wav': 'fa-file-audio',
        'txt': 'fa-file-lines',
    }
    return mapping.get(ext, 'fa-file')



@register.filter
def dept_short(value):
    """Returns only the sub-section part after ' — '.
    For head-office values with no sub-section, returns the display label instead."""
    if value and ' — ' in value:
        return value.split(' — ', 1)[1]
    if value:
        return _DEPT_LABELS.get(value, value)
    return '—'

@register.filter
def dept_parent(value):
    """Returns only the parent department before ' — '."""
    if value and ' — ' in value:
        return value.split(' — ', 1)[0]
    return value or '—'