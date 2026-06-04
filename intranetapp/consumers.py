import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Notification


class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope['user']
        if not user.is_authenticated:
            await self.close()
            return

        # Each user gets their own group: "notif_user_<pk>"
        self.group_name = f'notif_user_{user.pk}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send unread count immediately on connect
        count = await self.get_unread_count(user)
        await self.send(text_data=json.dumps({
            'type':         'unread_count',
            'unread_count': count,
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Receive message from WebSocket (e.g. mark-as-read ping from frontend)
    async def receive(self, text_data):
        data = json.loads(text_data)
        user = self.scope['user']

        if data.get('action') == 'mark_all_read':
            await self.mark_all_read(user)
            await self.send(text_data=json.dumps({'type': 'unread_count', 'unread_count': 0}))

        elif data.get('action') == 'mark_read' and data.get('id'):
            await self.mark_one_read(data['id'], user)
            count = await self.get_unread_count(user)
            await self.send(text_data=json.dumps({'type': 'unread_count', 'unread_count': count}))

        elif data.get('action') == 'fetch_recent':
            notifications = await self.get_recent(user)
            await self.send(text_data=json.dumps({
                'type':          'notification_list',
                'notifications': notifications,
            }))

    # ── Called by channel layer when someone pushes to this user's group ──
    async def send_notification(self, event):
        """Handler for group messages of type 'send_notification'."""
        await self.send(text_data=json.dumps({
            'type':          'new_notification',
            'id':            event['id'],
            'notif_type':    event['notif_type'],
            'title':         event['title'],
            'message':       event['message'],
            'url':           event['url'],
            'actor':         event.get('actor', ''),
            'created_at':    event['created_at'],
            'unread_count':  event['unread_count'],
        }))

    # ── DB helpers ──────────────────────────────────────────────────────────
    @database_sync_to_async
    def get_unread_count(self, user):
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @database_sync_to_async
    def mark_all_read(self, user):
        Notification.objects.filter(recipient=user, is_read=False).update(is_read=True)

    @database_sync_to_async
    def mark_one_read(self, notif_id, user):
        Notification.objects.filter(pk=notif_id, recipient=user).update(is_read=True)

    @database_sync_to_async
    def get_recent(self, user):
        qs = Notification.objects.filter(recipient=user).select_related('actor')[:20]
        return [
            {
                'id':         n.pk,
                'notif_type': n.notif_type,
                'title':      n.title,
                'message':    n.message,
                'url':        n.url,
                'is_read':    n.is_read,
                'actor':      n.actor.get_full_name() if n.actor else '',
                'created_at': n.created_at.strftime('%b %d, %Y %I:%M %p'),
            }
            for n in qs
        ]