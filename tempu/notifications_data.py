"""Static notification inbox items (captured from the live TEMP-U inbox).

Read-state is tracked per-user in the settings table (key 'notif_read_ids',
a JSON list of read ids), so no DB rebuild is needed to use notifications.
"""

NOTIFICATIONS = [
    {"id": "n-lib-expiry", "category": "Access and subscriptions", "priority": "high",
     "title": "Library access is ending soon",
     "body": "Your library access ends on 27 Nov 2026.",
     "action_url": "/billing", "action_label": "Review access", "date": "20 Nov",
     "required": True},
    {"id": "n-flashcards", "category": "Flashcards",
     "title": "Flashcards are now on every topic",
     "body": "Every Step 1 and Step 2 CK topic now has ready-made flashcards, written "
             "for the content you just read. Tap the cards icon at the top of any topic "
             "to start a quick review. Mark what you missed, then save those cards to your "
             "own deck to study later.",
     "action_url": "/flashcards/library", "action_label": "Read more", "date": "2 Nov"},
    {"id": "n-vertigo", "category": "New feature",
     "title": "Updated section: Vertigo",
     "body": "This section has been rewritten for more clarity. New illustrations have been added.",
     "action_url": None, "action_label": None, "date": "29 Oct"},
    {"id": "n-preterm", "category": "Step 2 CK",
     "title": "Updated section: Pre- & Post-term Delivery",
     "body": "This section has been rewritten for more clarity with updated visuals and better formatting.",
     "action_url": None, "action_label": "Read more", "date": "29 Oct"},
    {"id": "n-dyslipidemias", "category": "Step 2 CK",
     "title": "Updated topic: Genetic dyslipidemias",
     "body": "We added a newly mentioned topic in UWorld which is Lipoprotein(a) [Lp(a)]. "
             "Enjoy studying, we got your back! TEMPU content team",
     "action_url": None, "action_label": "Read more", "date": "29 Oct"},
    {"id": "n-operative", "category": "Step 2 CK",
     "title": "Updated section: Operative Labor and Delivery",
     "body": "This section has been rewritten for more clarity.",
     "action_url": None, "action_label": None, "date": "29 Oct"},
    {"id": "n-ams", "category": "Step 2 CK",
     "title": "Updated section: Altered Mental Status & Disorders of Consciousness",
     "body": "Cleaner structure, updated brain death criteria, improved diagnostic approaches, "
             "and high-yield TEMPU notes covering delirium, PRES, coma, and disorders of consciousness!",
     "action_url": None, "action_label": "Read more", "date": "27 Oct"},
    {"id": "n-dementia", "category": "Step 2 CK",
     "title": "Updated section: Dementia",
     "body": "Cleaner structure, updated diagnostic and management approaches, new illustrations, "
             "and high-yield TEMPU notes to help differentiate dementia subtypes!",
     "action_url": None, "action_label": "Read more", "date": "27 Oct"},
    {"id": "n-nmd", "category": "Step 2 CK",
     "title": "Updated section: Neuromuscular Diseases",
     "body": "Cleaner structure, new illustrations, improved MG vs LEMS comparisons, "
             "and high-yield TEMPU notes and exam traps!",
     "action_url": None, "action_label": "Read more", "date": "27 Oct"},
    {"id": "n-gait", "category": "Step 2 CK",
     "title": "Updated section: Gait/Cerebellar Disorders",
     "body": "Cleaner structure, improved gait comparisons, new illustrations, and more high-yield notes!",
     "action_url": None, "action_label": None, "date": "27 Oct"},
]
