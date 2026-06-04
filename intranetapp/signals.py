from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Notification

channel_layer = get_channel_layer()


def _push_to_user(user, notif):
    group = f'notif_user_{user.pk}'
    unread = Notification.objects.filter(recipient=user, is_read=False).count()
    async_to_sync(channel_layer.group_send)(
        group,
        {
            'type':         'send_notification',
            'id':           notif.pk,
            'notif_type':   notif.notif_type,
            'title':        notif.title,
            'message':      notif.message,
            'url':          notif.url,
            'actor':        notif.actor.get_full_name() if notif.actor else '',
            'created_at':   notif.created_at.strftime('%b %d, %Y %I:%M %p'),
            'unread_count': unread,
        }
    )


def _broadcast(actor, notif_type, title, message, url):
    recipients = User.objects.filter(is_active=True).exclude(pk=actor.pk)
    for user in recipients:
        notif = Notification.objects.create(
            recipient=user,
            actor=actor,
            notif_type=notif_type,
            title=title,
            message=message,
            url=url,
        )
        _push_to_user(user, notif)



# ── Press Releases ─────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.PressRelease')
def on_press_release_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'published a new' if created else 'updated a'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_PRESS_RELEASE,
            title=f'{actor.get_full_name() or actor.username} {verb} press release',
            message=instance.title,
            url=f'/press-releases/{instance.pk}/',
        )


# ── Events ─────────────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.Event')
def on_event_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'created a new' if created else 'updated an'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_EVENT,
            title=f'{actor.get_full_name() or actor.username} {verb} event',
            message=instance.title,
            url='/events-trainings/',
        )


# ── Trainings ──────────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.Training')
def on_training_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'created a new' if created else 'updated a'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_TRAINING,
            title=f'{actor.get_full_name() or actor.username} {verb} training',
            message=instance.title,
            url='/events-trainings/?tab=tr',
        )


# ── Issuances ──────────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.Issuance')
def on_issuance_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'issued a new' if created else 'updated an'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_ISSUANCE,
            title=f'{actor.get_full_name() or actor.username} {verb} issuance',
            message=instance.issuance_no,
            url='/issuances/',
        )


# ── Wiki ───────────────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.WikiArticle')
def on_wiki_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'published a new' if created else 'updated a'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_WIKI,
            title=f'{actor.get_full_name() or actor.username} {verb} wiki article',
            message=instance.title,
            url='/wiki/',
        )


# ── Downloads ──────────────────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.Download')
def on_download_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'uploaded a new' if created else 'updated a'
        actor = instance.author
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_DOWNLOAD,
            title=f'{actor.get_full_name() or actor.username} {verb} download',
            message=instance.title,
            url=f'/downloads/?tab={instance.tab}',
        )


# ── Employee Corner Posts ──────────────────────────────────────────────────────
@receiver(post_save, sender='intranetapp.EmployeeCornerPost')
def on_corner_post_save(sender, instance, created, **kwargs):
    if instance.status == 'published':
        verb = 'posted in' if created else 'updated a post in'
        actor = instance.author
        section = instance.category.title()
        _broadcast(
            actor=actor,
            notif_type=Notification.TYPE_CORNER_POST,
            title=f'{actor.get_full_name() or actor.username} {verb} {section} Corner',
            message=instance.title,
            url=f'/employees-corner/?tab={instance.category}',
        )