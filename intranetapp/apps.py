from django.apps import AppConfig


class IntranetappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'intranetapp'


class IntranetAppConfig(AppConfig):
    name = 'intranetapp'

    def ready(self):
        # Import signals to ensure they are registered
        import intranetapp.signals