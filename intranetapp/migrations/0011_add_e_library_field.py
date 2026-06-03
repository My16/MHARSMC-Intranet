from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('intranetapp', '0010_role_role_management_role_settings_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='e_library',
            field=models.CharField(choices=[('none', 'None'), ('view', 'View Only'), ('edit', 'Edit')], default='none', max_length=10),
        ),
    ]
