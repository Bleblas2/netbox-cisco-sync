"""Wspólne zestawy wyborów dla modeli, formularzy, tabel i silnika synchronizacji."""

from utilities.choices import ChoiceSet


class MatchMethodChoices(ChoiceSet):
    MANUAL = "manual"
    CUSTOM_FIELD = "custom_field"
    NAME = "name"
    GPS = "gps"
    UNMATCHED = "unmatched"

    CHOICES = (
        (MANUAL, "Manual", "blue"),
        (CUSTOM_FIELD, "SdwanSiteId", "green"),
        (NAME, "Site name", "cyan"),
        (GPS, "GPS", "purple"),
        (UNMATCHED, "Unmatched", "orange"),
    )


class SyncModeChoices(ChoiceSet):
    COMPARE = "compare"
    APPLY = "apply"
    CHOICES = ((COMPARE, "Compare", "cyan"), (APPLY, "Apply", "green"))


class SyncStatusChoices(ChoiceSet):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    CHOICES = ((OK, "OK", "green"), (FAILED, "Failed", "red"), (SKIPPED, "Skipped", "gray"))


class SyncTriggerChoices(ChoiceSet):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    CHOICES = ((MANUAL, "Manual", "blue"), (SCHEDULED, "Scheduled", "purple"))
