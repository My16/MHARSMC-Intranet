from django import forms
from django.contrib.auth.models import User
from .models import UserProfile


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']


class UserEditForm(forms.ModelForm):
    """Form for editing users — no password field (handled separately)."""
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['middle_name', 'position', 'department', 'role', 'avatar']
