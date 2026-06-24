from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Auth
    path('login/',  views.login,        name='login'),
    path('logout/', views.logout_view,  name='logout'),
    path('register/', views.register,     name='register'),
    path('',        views.home,         name='home'),

    # User Management
    path('users/',                  views.user_management, name='user_management'),
    path('users/add/',              views.user_add,        name='user_add'),
    path('users/<int:pk>/edit/',    views.user_edit,       name='user_edit'),
    path('users/<int:pk>/toggle/',  views.user_toggle,     name='user_toggle'),
    path('users/<int:pk>/delete/',  views.user_delete,     name='user_delete'),
    path('users/<int:pk>/approve/', views.user_approve, name='user_approve'),

    # Role Management
    path('roles/',                  views.role_management, name='role_management'),
    path('roles/add/',              views.role_add,        name='role_add'),
    path('roles/<int:pk>/edit/',    views.role_edit,       name='role_edit'),
    path('roles/<int:pk>/delete/',  views.role_delete,     name='role_delete'),

    # Press Releases
    path('press-releases/',                          views.press_releases,                name='press_releases'),
    path('press-releases/create/',                   views.press_release_create,          name='press_release_create'),
    path('press-releases/<int:pk>/edit/',             views.press_release_edit,            name='press_release_edit'),
    path('press-releases/<int:pk>/delete/',           views.press_release_delete,          name='press_release_delete'),
    path('press-releases/<int:pk>/toggle-status/',    views.press_release_toggle_status,   name='press_release_toggle_status'),
    path('press-releases/<int:pk>/',                  views.press_release_detail,          name='press_release_detail'),

    # Events & Trainings
    path('events-trainings/', views.events_trainings, name='events_trainings'),
    path('events/create/',                   views.event_create,            name='event_create'),
    path('events/<int:pk>/edit/',            views.event_edit,              name='event_edit'),
    path('events/<int:pk>/delete/',          views.event_delete,            name='event_delete'),
    path('events/<int:pk>/toggle-status/',   views.event_toggle_status,     name='event_toggle_status'),
    path('events/attachment/<int:pk>/delete/', views.event_attachment_delete, name='event_attachment_delete'),

    # ── Trainings ──────────────────────────────────────────────────────────
    path('trainings/',                          views.trainings,               name='trainings'),
    path('trainings/create/',                   views.training_create,         name='training_create'),
    path('trainings/<int:pk>/edit/',            views.training_edit,           name='training_edit'),
    path('trainings/<int:pk>/delete/',          views.training_delete,         name='training_delete'),
    path('trainings/<int:pk>/toggle-status/',   views.training_toggle_status,  name='training_toggle_status'),

    # Issuances
    path('issuances/',                                views.issuances,                   name='issuances'),
    path('issuances/create/',                         views.issuance_create,             name='issuance_create'),
    path('issuances/<int:pk>/edit/',                  views.issuance_edit,               name='issuance_edit'),
    path('issuances/<int:pk>/delete/',                views.issuance_delete,             name='issuance_delete'),
    path('issuances/<int:pk>/toggle-status/',         views.issuance_toggle_status,      name='issuance_toggle_status'),
    # Issuance Categories
    path('issuances/categories/add/',                 views.issuance_category_add,       name='issuance_category_add'),
    path('issuances/categories/<int:pk>/edit/',       views.issuance_category_edit,      name='issuance_category_edit'),
    path('issuances/categories/<int:pk>/delete/',     views.issuance_category_delete,    name='issuance_category_delete'),

    # Main list / tabs
    path('wiki/',                              views.wiki,               name='wiki'),
 
    # Article CRUD
    path('wiki/create/',                       views.wiki_create,        name='wiki_create'),
    path('wiki/<int:pk>/edit/',                views.wiki_edit,          name='wiki_edit'),
    path('wiki/<int:pk>/delete/',              views.wiki_delete,        name='wiki_delete'),
    path('wiki/<int:pk>/toggle-status/',       views.wiki_toggle_status, name='wiki_toggle_status'),
 
    # Tag CRUD
    path('wiki/tags/add/',                     views.wiki_tag_add,       name='wiki_tag_add'),
    path('wiki/tags/<int:pk>/edit/',           views.wiki_tag_edit,      name='wiki_tag_edit'),
    path('wiki/tags/<int:pk>/delete/',         views.wiki_tag_delete,    name='wiki_tag_delete'),

    # Employees Corner
    path('employees-corner/',                                  views.employees_corner,            name='employees_corner'),
    path('employees-corner/create/<str:section>/',             views.corner_post_create,          name='corner_post_create'),
    path('employees-corner/<str:section>/<int:pk>/edit/',      views.corner_post_edit,            name='corner_post_edit'),
    path('employees-corner/<str:section>/<int:pk>/delete/',    views.corner_post_delete,          name='corner_post_delete'),
    path('employees-corner/<str:section>/<int:pk>/toggle-status/', views.corner_post_toggle_status, name='corner_post_toggle_status'),

    # Applications
    path('applications/',                          views.applications,                name='applications'),
    path('applications/create/',                   views.application_create,          name='application_create'),
    path('applications/<int:pk>/edit/',            views.application_edit,            name='application_edit'),
    path('applications/<int:pk>/delete/',          views.application_delete,          name='application_delete'),
    path('applications/<int:pk>/toggle-status/',   views.application_toggle_status,   name='application_toggle_status'),

    # Directory
    path('directory/',                    views.directory,     name='directory'),
    path('directory/offices/add/',        views.office_add,    name='office_add'),
    path('directory/offices/<int:pk>/edit/',   views.office_edit,   name='office_edit'),
    path('directory/offices/<int:pk>/delete/', views.office_delete, name='office_delete'),


    # Downloads
    path('downloads/',                              views.downloads,                name='downloads'),
    path('downloads/create/',                       views.download_create,          name='download_create'),
    path('downloads/<int:pk>/edit/',                views.download_edit,            name='download_edit'),
    path('downloads/<int:pk>/delete/',              views.download_delete,          name='download_delete'),
    path('downloads/<int:pk>/toggle-status/',       views.download_toggle_status,   name='download_toggle_status'),
    path('downloads/categories/add/',               views.download_category_add,    name='download_category_add'),
    path('downloads/categories/<int:pk>/edit/',     views.download_category_edit,   name='download_category_edit'),
    path('downloads/categories/<int:pk>/delete/',   views.download_category_delete, name='download_category_delete'),
    path('downloads/tags/add/',                     views.download_tag_add,         name='download_tag_add'),
    path('downloads/tags/<int:pk>/edit/',           views.download_tag_edit,        name='download_tag_edit'),
    path('downloads/tags/<int:pk>/delete/',         views.download_tag_delete,      name='download_tag_delete'),

    # Settings
    path('settings/',          views.settings_profile,  name='settings_profile'),
    path('settings/password/', views.settings_password, name='settings_password'),

    # Notifications
    path('notifications/',           views.notifications_list,           name='notifications_list'),
    path('notifications/mark-read/', views.notifications_mark_all_read,  name='notifications_mark_read'),
    
    # Messenger
    path('messenger/',                                  views.messenger,                name='messenger'),
    path('messenger/users/',                            views.messenger_users,          name='messenger_users'),
    path('messenger/conversations/',                    views.messenger_conversations,  name='messenger_conversations'),
    path('messenger/conversations/start/',              views.messenger_start,          name='messenger_start'),
    path('messenger/conversations/<int:conv_id>/messages/', views.messenger_messages,  name='messenger_messages'),
    path('messenger/conversations/<int:conv_id>/send/',     views.messenger_send,      name='messenger_send'),
    path('messenger/conversations/<int:conv_id>/read/', views.messenger_read,           name='messenger_read'),
    path('messenger/conversations/<int:conv_id>/delete/', views.messenger_delete_conversation, name='messenger_delete_conversation'),

    # Group Messenger
    path('messenger/conversations/create-group/',                   views.messenger_create_group,        name='messenger_create_group'),
    path('messenger/conversations/<int:conv_id>/add-members/',      views.messenger_group_add_members,   name='messenger_group_add_members'),
    path('messenger/conversations/<int:conv_id>/remove-member/',    views.messenger_group_remove_member, name='messenger_group_remove_member'),
    path('messenger/conversations/<int:conv_id>/update-group/',     views.messenger_group_update,        name='messenger_group_update'),
    path('messenger/conversations/<int:conv_id>/leave/',        views.messenger_leave_group,         name='messenger_group_leave'),
    # Mute
    path('messenger/conversations/<int:conv_id>/mute/',   views.messenger_mute,      name='messenger_mute'),
    path('messenger/conversations/<int:conv_id>/unmute/', views.messenger_unmute,    name='messenger_unmute'),
    # Archive
    path('messenger/conversations/<int:conv_id>/archive/',   views.messenger_archive,   name='messenger_archive'),
    path('messenger/conversations/<int:conv_id>/unarchive/', views.messenger_unarchive, name='messenger_unarchive'),
    # Block
    path('messenger/users/<int:user_id>/block/',   views.messenger_block,   name='messenger_block'),
    path('messenger/users/<int:user_id>/unblock/', views.messenger_unblock, name='messenger_unblock'),
    path('messenger/conversations/<int:conv_id>/messages/<int:msg_id>/unsend/', views.messenger_unsend, name='messenger_unsend'),


] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)