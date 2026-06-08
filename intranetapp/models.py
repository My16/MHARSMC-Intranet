from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


PERM_NONE = 'none'
PERM_VIEW = 'view'
PERM_EDIT = 'edit'
PERM_CHOICES = [
    (PERM_NONE, 'None'),
    (PERM_VIEW, 'View Only'),
    (PERM_EDIT, 'Edit'),
]

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')

    # Module permissions — 'none', 'view', or 'edit'
    press_releases   = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    events_trainings = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    issuances        = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    wiki             = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    e_library        = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    employees_corner = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    applications     = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    directory        = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    downloads        = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    user_management  = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    role_management  = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)
    settings         = models.CharField(max_length=10, choices=PERM_CHOICES, default=PERM_NONE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_administrator(self):
        return self.name.strip().lower() == 'administrator'

    def has_access(self, module_key):
        """True if the role can view OR edit the module."""
        if self.is_administrator:
            return True
        return getattr(self, module_key, PERM_NONE) in (PERM_VIEW, PERM_EDIT)

    def can_edit(self, module_key):
        """True only if the role has full edit access."""
        if self.is_administrator:
            return True
        return getattr(self, module_key, PERM_NONE) == PERM_EDIT

    def as_dict(self):
        from .views import MODULE_KEYS
        return {k: getattr(self, k, PERM_NONE) for k in MODULE_KEYS}

    def get_module_perms_list(self):
        """Returns list of 'none'/'view'/'edit' in MODULE_KEYS order for JS."""
        from .views import MODULE_KEYS
        if self.is_administrator:
            return [PERM_EDIT for _ in MODULE_KEYS]
        return [getattr(self, k, PERM_NONE) for k in MODULE_KEYS]

    @property
    def user_count(self):
        return self.userprofile_set.filter(user__is_superuser=False).count()
    
    @property
    def has_any_access(self):
        """True if at least one module is set to view or edit."""
        from .views import MODULE_KEYS
        return any(getattr(self, k, PERM_NONE) != PERM_NONE for k in MODULE_KEYS)


DEPARTMENT_CHOICES = [
    # Office of the Medical Center Chief
    ("Office of the Medical Center Chief — Legal Unit",                              "Legal Unit (MCC Office)"),
    ("Office of the Medical Center Chief — Public Health Unit",                      "Public Health Unit (MCC Office)"),
    ("Office of the Medical Center Chief — Planning and Management Unit",            "Planning and Management Unit (MCC Office)"),
    ("Office of the Medical Center Chief — Office of Strategic Management",          "Office of Strategic Management (MCC Office)"),
    ("Office of the Medical Center Chief — Professional Education, Training and Research", "Professional Education, Training and Research (MCC Office)"),
    ("Office of the Medical Center Chief — Health Emergency and Disaster Management Unit", "Health Emergency and Disaster Management Unit (MCC Office)"),
    # Allied Health Professional Service
    ("Allied Health Professional Service — Nutrition and Dietetics Department",      "Nutrition and Dietetics Department"),
    ("Allied Health Professional Service — Pharmacy Department",                     "Pharmacy Department"),
    ("Allied Health Professional Service — Medical Social Work Department",          "Medical Social Work Department"),
    ("Allied Health Professional Service — Health Information Management Department","Health Information Management Department"),
    # Nursing Service
    ("Nursing Service — Clinical Nursing Units",    "Clinical Nursing Units"),
    ("Nursing Service — Operating Room",            "Operating Room"),
    ("Nursing Service — Special Care Areas",        "Special Care Areas"),
    ("Nursing Service — Obstetric Complex",         "Obstetric Complex"),
    ("Nursing Service — Emergency Room",            "Emergency Room"),
    ("Nursing Service — Outpatient Department",     "Outpatient Department"),
    ("Nursing Service — Dialysis Unit",             "Dialysis Unit"),
    # HOPSS
    ("HOPSS — Human Resource Management Section",                           "Human Resource Management Section"),
    ("HOPSS — Procurement Section",                                         "Procurement Section"),
    ("HOPSS — Materials Management Section",                                "Materials Management Section"),
    ("HOPSS — Integrated Management Information System Section",            "Integrated Management Information System Section"),
    ("HOPSS — Security",                                                    "Security"),
    ("HOPSS — Engineering and Facilities Management Section",               "Engineering and Facilities Management Section"),
    ("HOPSS — Housekeeping, Linen, and Laundry",                            "Housekeeping, Linen, and Laundry"),
    # Finance Service
    ("Finance Service — Billing and Claims Section",                        "Billing and Claims Section"),
    ("Finance Service — Accounting Section",                                "Accounting Section"),
    ("Finance Service — Budget Section",                                    "Budget Section"),
    ("Finance Service — Cash Operations Section",                           "Cash Operations Section"),
    ("Finance Service — Health Insurance Medical Evaluation Unit",          "Health Insurance Medical Evaluation Unit"),
]


GENDER_CHOICES = [
    ('male',           'Male'),
    ('female',         'Female'),
    ('non_binary',     'Non-Binary'),
    ('prefer_not',     'Prefer not to say'),
    ('self_describe',  'Let me describe'),
]


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )

    middle_name = models.CharField(max_length=100, blank=True, default='')

    position = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='Position/Designation'
    )

    # ForeignKey to Role — null allowed so we can handle orphaned users gracefully
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='userprofile_set',
    )

    department = models.CharField(
        max_length=200,
        blank=True,
        default='',
        choices=DEPARTMENT_CHOICES,
        verbose_name='Department',
    )

    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    mobile_number = models.CharField(
        max_length=30,
        blank=True,
        default='',
        verbose_name='Mobile Number',
    )

    gender = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=GENDER_CHOICES,
        verbose_name='Gender',
    )

    gender_self_describe = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Gender Self Description',
    )

    bio = models.TextField(
        blank=True,
        default='',
        verbose_name='Bio',
    )

    is_online = models.BooleanField(default=False)

    def __str__(self):
        role_name = self.role.name if self.role else 'No Role'
        return f"{self.user.username} — {role_name}"

    def get_full_name_with_middle(self):
        parts = [
            self.user.first_name,
            self.middle_name,
            self.user.last_name,
        ]
        return ' '.join(p for p in parts if p).strip() or self.user.username

    @property
    def is_administrator(self):
        return self.role is not None and self.role.is_administrator

    def has_module_access(self, module_key):
        if self.role is None:
            return False
        return self.role.has_access(module_key)

    def can_edit_module(self, module_key):
        if self.role is None:
            return False
        return self.role.can_edit(module_key)

    # Keep get_role_display compatible with templates that used the old CharField
    def get_role_display(self):
        return self.role.name if self.role else '—'
    

class PressRelease(models.Model):
 
    # ── Status choices ─────────────────────────────────────────────────────────
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]
 
    # ── Archive policy choices ─────────────────────────────────────────────────
    ARCHIVE_DEFAULT    = 'default'
    ARCHIVE_ON_DATE    = 'on_date'
    ARCHIVE_NEVER      = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]
 
    # ── Fields ─────────────────────────────────────────────────────────────────
    title           = models.CharField(max_length=300)
    slug            = models.SlugField(max_length=320, unique=True, blank=True)
    details         = models.TextField()
    image           = models.ImageField(upload_to='press_releases/', blank=True, null=True)
 
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
 
    archive_policy  = models.CharField(max_length=20, choices=ARCHIVE_CHOICES, default=ARCHIVE_DEFAULT)
    archive_date    = models.DateField(blank=True, null=True,
                                       help_text='Only used when archive_policy = on_date')
 
    author          = models.ForeignKey(
                          User,
                          on_delete=models.SET_NULL,
                          null=True, blank=True,
                          related_name='press_releases'
                      )
 
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    published_at    = models.DateTimeField(blank=True, null=True)
 
    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Press Release'
        verbose_name_plural = 'Press Releases'
 
    def __str__(self):
        return self.title
 
    # ── Helpers ────────────────────────────────────────────────────────────────
    def save(self, *args, **kwargs):
        # Auto-generate slug from title + uuid fragment if blank
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.title)[:280]
            self.slug = f"{base}-{uuid.uuid4().hex[:6]}"
        # Set published_at timestamp on first publish
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
 
    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT
 
    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED
 
    @property
    def is_archived(self):
        return self.status == self.STATUS_ARCHIVED
 
    def get_status_badge_class(self):
        return {
            self.STATUS_DRAFT:     'badge-draft',
            self.STATUS_PUBLISHED: 'badge-published',
            self.STATUS_ARCHIVED:  'badge-archived',
        }.get(self.status, '')


class Event(models.Model):
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]

    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]

    title          = models.CharField(max_length=300)
    location       = models.CharField(max_length=300)
    summary        = models.CharField(max_length=500, blank=True, default='')
    details        = models.TextField()

    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    start_date     = models.DateField()
    end_date       = models.DateField(blank=True, null=True)
    start_time     = models.TimeField(blank=True, null=True)
    end_time       = models.TimeField(blank=True, null=True)

    archive_policy = models.CharField(max_length=20, choices=ARCHIVE_CHOICES, default=ARCHIVE_DEFAULT)
    archive_date   = models.DateField(blank=True, null=True,
                                     help_text='Only used when archive_policy = on_date')

    author         = models.ForeignKey(
                        User,
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='events'
                    )

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    published_at   = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-start_date', '-created_at']
        verbose_name        = 'Event'
        verbose_name_plural = 'Events'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_archived(self):
        return self.status == self.STATUS_ARCHIVED

    def get_status_badge_class(self):
        return {
            self.STATUS_DRAFT:     'badge-draft',
            self.STATUS_PUBLISHED: 'badge-published',
            self.STATUS_ARCHIVED:  'badge-archived',
        }.get(self.status, '')


class EventAttachment(models.Model):
    event         = models.ForeignKey(
                        'Event',
                        on_delete=models.CASCADE,
                        related_name='attachments'
                    )
    file          = models.FileField(upload_to='event_attachments/')
    original_name = models.CharField(max_length=255)
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name        = 'Event Attachment'
        verbose_name_plural = 'Event Attachments'

    def __str__(self):
        return self.original_name

    @property
    def file_size_display(self):
        size = self.file.size if self.file and hasattr(self.file, 'size') else 0
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"



class Training(models.Model):

    # ── Status choices ────────────────────────────────────────────────────────
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]

    # ── Archive policy choices ────────────────────────────────────────────────
    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]

    # ── Core fields ───────────────────────────────────────────────────────────
    title                = models.CharField(max_length=300)
    location             = models.CharField(max_length=300)
    summary              = models.CharField(max_length=500, blank=True, default='')
    details              = models.TextField()

    # Training-specific fields
    organizer            = models.CharField(max_length=300)
    target_participants  = models.CharField(max_length=500)
    requirements         = models.TextField(blank=True, default='')
    contact_details      = models.CharField(max_length=500, blank=True, default='')

    # ── Status / lifecycle ────────────────────────────────────────────────────
    status               = models.CharField(
                               max_length=20,
                               choices=STATUS_CHOICES,
                               default=STATUS_DRAFT,
                           )

    # ── Schedule ──────────────────────────────────────────────────────────────
    start_date           = models.DateField()
    end_date             = models.DateField(blank=True, null=True)
    start_time           = models.TimeField(blank=True, null=True)
    end_time             = models.TimeField(blank=True, null=True)

    # ── Archiving ─────────────────────────────────────────────────────────────
    archive_policy       = models.CharField(
                               max_length=20,
                               choices=ARCHIVE_CHOICES,
                               default=ARCHIVE_DEFAULT,
                           )
    archive_date         = models.DateField(
                               blank=True, null=True,
                               help_text='Only used when archive_policy = on_date',
                           )

    # ── Authorship ────────────────────────────────────────────────────────────
    author               = models.ForeignKey(
                               User,
                               on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name='trainings',
                           )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)
    published_at         = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering            = ['-start_date', '-created_at']
        verbose_name        = 'Training'
        verbose_name_plural = 'Trainings'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    # ── Status helpers ────────────────────────────────────────────────────────
    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_archived(self):
        return self.status == self.STATUS_ARCHIVED

    def get_status_badge_class(self):
        return {
            self.STATUS_DRAFT:     'badge-draft',
            self.STATUS_PUBLISHED: 'badge-published',
            self.STATUS_ARCHIVED:  'badge-archived',
        }.get(self.status, '')


class TrainingAttachment(models.Model):
    training      = models.ForeignKey(
                        'Training',
                        on_delete=models.CASCADE,
                        related_name='attachments',
                    )
    file          = models.FileField(upload_to='training_attachments/')
    original_name = models.CharField(max_length=255)
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['-uploaded_at']
        verbose_name        = 'Training Attachment'
        verbose_name_plural = 'Training Attachments'

    def __str__(self):
        return self.original_name

    @property
    def file_size_display(self):
        size = self.file.size if self.file and hasattr(self.file, 'size') else 0
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    

class IssuanceCategory(models.Model):
    """
    Categories for issuances.
    Pre-seeded: Administrative Order, Department Memorandum,
                Department Circular, Memorandum Circular.
    Admins can add their own.
    """
    name       = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering            = ['name']
        verbose_name        = 'Issuance Category'
        verbose_name_plural = 'Issuance Categories'
 
    def __str__(self):
        return self.name
 
    @property
    def issuance_count(self):
        return self.issuances.count()
 
 
class Issuance(models.Model):
    """
    Official issuances (orders, circulars, memoranda, etc.).
    """
 
    # ── Status choices ────────────────────────────────────────────────────────
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]
 
    # ── Archive policy choices ────────────────────────────────────────────────
    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]
 
    # ── Core fields ───────────────────────────────────────────────────────────
    issuance_no   = models.CharField(
        max_length=200,
        verbose_name='Issuance No.',
        help_text='Unique reference number, e.g. AO-2024-001',
    )
    category      = models.ForeignKey(
        IssuanceCategory,
        on_delete=models.PROTECT,
        related_name='issuances',
        verbose_name='Category',
    )
    issuance_date = models.DateField(verbose_name='Issuance Date')
    summary       = models.TextField(verbose_name='Summary')
    attachment    = models.FileField(
        upload_to='issuances/',
        verbose_name='Attachment',
        blank=True,
        null=True,
    )
 
    # ── Status / lifecycle ────────────────────────────────────────────────────
    status        = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
 
    # ── Archiving ─────────────────────────────────────────────────────────────
    archive_policy = models.CharField(
        max_length=20,
        choices=ARCHIVE_CHOICES,
        default=ARCHIVE_DEFAULT,
    )
    archive_date   = models.DateField(
        blank=True,
        null=True,
        help_text='Only used when archive_policy = on_date',
    )
 
    # ── Authorship ────────────────────────────────────────────────────────────
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issuances',
    )
 
    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(blank=True, null=True)
 
    class Meta:
        ordering            = ['-issuance_date', '-created_at']
        verbose_name        = 'Issuance'
        verbose_name_plural = 'Issuances'
 
    def __str__(self):
        return f'{self.issuance_no} — {self.category}'
 
    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
 
    # ── Status helpers ────────────────────────────────────────────────────────
    @property
    def is_draft(self):      return self.status == self.STATUS_DRAFT
 
    @property
    def is_published(self):  return self.status == self.STATUS_PUBLISHED
 
    @property
    def is_archived(self):   return self.status == self.STATUS_ARCHIVED
 
    def get_status_badge_class(self):
        return {
            self.STATUS_DRAFT:     'badge-draft',
            self.STATUS_PUBLISHED: 'badge-published',
            self.STATUS_ARCHIVED:  'badge-archived',
        }.get(self.status, '')
 
    @property
    def attachment_name(self):
        if self.attachment:
            return self.attachment.name.split('/')[-1]
        return ''
 
    @property
    def file_size_display(self):
        if not self.attachment:
            return ''
        try:
            size = self.attachment.size
        except Exception:
            return ''
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f'{size:.0f} {unit}'
            size /= 1024.0
        return f'{size:.1f} TB'
    

class WikiTag(models.Model):
    """
    Tags for wiki articles. Created on the fly when authors type them,
    or managed explicitly via the Tags tab.
    """
    name       = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering            = ['name']
        verbose_name        = 'Wiki Tag'
        verbose_name_plural = 'Wiki Tags'
 
    def __str__(self):
        return self.name
 
    @property
    def wiki_count(self):
        return self.wiki_articles.count()
 
 
class WikiArticle(models.Model):
    """
    Knowledge-base articles with full-text article body, a reference field,
    and many-to-many tags.
    """
 
    # ── Status choices ────────────────────────────────────────────────────────
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]
 
    # ── Archive policy choices ────────────────────────────────────────────────
    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]
 
    # ── Core fields ───────────────────────────────────────────────────────────
    title     = models.CharField(max_length=300, verbose_name='Title')
    article   = models.TextField(verbose_name='Article')
    reference = models.CharField(
        max_length=500,
        verbose_name='Reference',
        help_text='e.g. RA 11032, Section 4 / https://...',
    )
    tags      = models.ManyToManyField(
        WikiTag,
        blank=True,
        related_name='wiki_articles',
        verbose_name='Tags',
    )
 
    # ── Status / lifecycle ────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
 
    # ── Archiving ─────────────────────────────────────────────────────────────
    archive_policy = models.CharField(
        max_length=20,
        choices=ARCHIVE_CHOICES,
        default=ARCHIVE_DEFAULT,
    )
    archive_date = models.DateField(
        blank=True,
        null=True,
        help_text='Only used when archive_policy = on_date',
    )
 
    # ── Authorship ────────────────────────────────────────────────────────────
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wiki_articles',
    )
 
    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(blank=True, null=True)
 
    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Wiki Article'
        verbose_name_plural = 'Wiki Articles'
 
    def __str__(self):
        return self.title
 
    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
 
    # ── Status helpers ────────────────────────────────────────────────────────
    @property
    def is_draft(self):     return self.status == self.STATUS_DRAFT
 
    @property
    def is_published(self): return self.status == self.STATUS_PUBLISHED
 
    @property
    def is_archived(self):  return self.status == self.STATUS_ARCHIVED
 
    def get_status_badge_class(self):
        return {
            self.STATUS_DRAFT:     'badge-draft',
            self.STATUS_PUBLISHED: 'badge-published',
            self.STATUS_ARCHIVED:  'badge-archived',
        }.get(self.status, '')


# ── Employees Corner Models ───────────────────────────────────────────────────
class EmployeeCornerPost(models.Model):
    CATEGORY_UNION = 'union'
    CATEGORY_COOP  = 'coop'
    CATEGORY_CHOICES = [
        (CATEGORY_UNION, 'Union'),
        (CATEGORY_COOP,  'Cooperative'),
    ]

    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]

    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]

    title          = models.CharField(max_length=300)
    summary        = models.CharField(max_length=500, blank=True, default='')
    content        = models.TextField()
    category       = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_UNION)
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    date_posted    = models.DateField()
    archive_policy = models.CharField(max_length=20, choices=ARCHIVE_CHOICES, default=ARCHIVE_DEFAULT)
    archive_date   = models.DateField(blank=True, null=True,
                                      help_text='Only used when archive_policy = on_date')
    author         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='employee_corner_posts')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    published_at   = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-date_posted', '-created_at']
        verbose_name = 'Employee Corner Post'
        verbose_name_plural = 'Employee Corner Posts'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class PostAttachment(models.Model):
    post          = models.ForeignKey(EmployeeCornerPost, on_delete=models.CASCADE, related_name='attachments')
    file          = models.FileField(upload_to='employee_corner_attachments/')
    original_name = models.CharField(max_length=255)
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Post Attachment'
        verbose_name_plural = 'Post Attachments'

    def __str__(self):
        return self.original_name

    @property
    def file_size_display(self):
        size = self.file.size if self.file and hasattr(self.file, 'size') else 0
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


class Application(models.Model):
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
    ]

    title        = models.CharField(max_length=300)
    url          = models.URLField(max_length=500)
    description  = models.TextField()
    logo         = models.ImageField(upload_to='applications/logos/')
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    author       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Application'
        verbose_name_plural = 'Applications'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class Office(models.Model):
    name         = models.CharField(max_length=300, verbose_name='Office Name')
    local_number = models.CharField(max_length=100, verbose_name='Local Number')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['name']
        verbose_name        = 'Office'
        verbose_name_plural = 'Offices'

    def __str__(self):
        return self.name
    


class DownloadCategory(models.Model):
    name       = models.CharField(max_length=200, unique=True)
    tab        = models.CharField(
                     max_length=10,
                     choices=[('forms', 'Forms'), ('files', 'Files')],
                     default='forms',
                 )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['tab', 'name']
        verbose_name        = 'Download Category'
        verbose_name_plural = 'Download Categories'

    def __str__(self):
        return f'{self.name} ({self.get_tab_display()})'

    @property
    def download_count(self):
        return self.downloads.count()


class DownloadTag(models.Model):
    name       = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['name']
        verbose_name        = 'Download Tag'
        verbose_name_plural = 'Download Tags'

    def __str__(self):
        return self.name

    @property
    def download_count(self):
        return self.downloads.count()


class Download(models.Model):
    STATUS_DRAFT     = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED  = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT,     'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED,  'Archived'),
    ]

    ARCHIVE_DEFAULT = 'default'
    ARCHIVE_ON_DATE = 'on_date'
    ARCHIVE_NEVER   = 'never'
    ARCHIVE_CHOICES = [
        (ARCHIVE_DEFAULT, 'Use Default Policy'),
        (ARCHIVE_ON_DATE, 'Archive on specific date'),
        (ARCHIVE_NEVER,   'Do not archive'),
    ]

    TAB_FORMS = 'forms'
    TAB_FILES = 'files'
    TAB_CHOICES = [
        (TAB_FORMS, 'Forms'),
        (TAB_FILES, 'Files'),
    ]

    title          = models.CharField(max_length=300)
    tab            = models.CharField(max_length=10, choices=TAB_CHOICES, default=TAB_FORMS, db_index=True)
    category       = models.ForeignKey(
                         DownloadCategory,
                         on_delete=models.PROTECT,
                         related_name='downloads',
                     )
    tags           = models.ManyToManyField(
                         DownloadTag,
                         blank=True,
                         related_name='downloads',
                     )
    attachment     = models.FileField(upload_to='downloads/')
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    archive_policy = models.CharField(max_length=20, choices=ARCHIVE_CHOICES, default=ARCHIVE_DEFAULT)
    archive_date   = models.DateField(blank=True, null=True)
    author         = models.ForeignKey(
                         User,
                         on_delete=models.SET_NULL,
                         null=True, blank=True,
                         related_name='downloads',
                     )
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    published_at   = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Download'
        verbose_name_plural = 'Downloads'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_draft(self):     return self.status == self.STATUS_DRAFT
    @property
    def is_published(self): return self.status == self.STATUS_PUBLISHED
    @property
    def is_archived(self):  return self.status == self.STATUS_ARCHIVED

    @property
    def attachment_name(self):
        if self.attachment:
            return self.attachment.name.split('/')[-1]
        return ''

    @property
    def file_size_display(self):
        if not self.attachment:
            return ''
        try:
            size = self.attachment.size
        except Exception:
            return ''
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f'{size:.0f} {unit}'
            size /= 1024.0
        return f'{size:.1f} TB'

    @property
    def file_extension(self):
        if self.attachment:
            name = self.attachment.name
            if '.' in name:
                return name.rsplit('.', 1)[1].lower()
        return ''
    


class Notification(models.Model):
    TYPE_PRESS_RELEASE = 'press_release'
    TYPE_EVENT         = 'event'
    TYPE_TRAINING      = 'training'
    TYPE_ISSUANCE      = 'issuance'
    TYPE_WIKI          = 'wiki'
    TYPE_DOWNLOAD      = 'download'
    TYPE_APPLICATION   = 'application'
    TYPE_CORNER_POST   = 'corner_post'

    TYPE_CHOICES = [
        (TYPE_PRESS_RELEASE, 'Press Release'),
        (TYPE_EVENT,         'Event'),
        (TYPE_TRAINING,      'Training'),
        (TYPE_ISSUANCE,      'Issuance'),
        (TYPE_WIKI,          'Wiki Article'),
        (TYPE_DOWNLOAD,      'Download'),
        (TYPE_APPLICATION,   'Application'),
        (TYPE_CORNER_POST,   'Employee Corner Post'),
    ]

    recipient   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notif_type  = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title       = models.CharField(max_length=255)
    message     = models.TextField(blank=True)
    url         = models.CharField(max_length=500, blank=True)
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)
    actor       = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='sent_notifications'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.notif_type}] → {self.recipient.username}: {self.title}'
    



class Conversation(models.Model):
    participants = models.ManyToManyField(User, related_name='conversations')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

class Message(models.Model):
    STATUS_SENT      = 'sent'
    STATUS_DELIVERED = 'delivered'
    STATUS_SEEN      = 'seen'
    STATUS_CHOICES   = [
        (STATUS_SENT,      'Sent'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_SEEN,      'Seen'),
    ]

    conversation    = models.ForeignKey('Conversation', on_delete=models.CASCADE, related_name='messages')
    sender          = models.ForeignKey(User, on_delete=models.CASCADE)
    body            = models.TextField(blank=True)
    attachment      = models.FileField(upload_to='messenger/', blank=True, null=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    is_read         = models.BooleanField(default=False)
    status          = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SENT)
    created_at      = models.DateTimeField(auto_now_add=True)

    @property
    def is_image(self):
        if not self.attachment:
            return False
        ext = self.attachment.name.split('.')[-1].lower()
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'svg')

    @property
    def file_extension(self):
        if self.attachment:
            return self.attachment.name.split('.')[-1].lower()
        return ''