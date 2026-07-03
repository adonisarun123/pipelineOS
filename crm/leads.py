"""Leads module models (L-1..L-6). Separate file for review clarity; same app."""
from django.conf import settings
from django.db import models

from tenants.models import TenantModel

from .models import Deal, LostReason, Organization, Person


class LeadSource(TenantModel):
    """L-2: configurable per tenant. token secures the L-7 capture endpoint;
    sla_minutes drives L-8 first-response timers."""

    name = models.CharField(max_length=100)
    token = models.CharField(max_length=48, blank=True, db_index=True)  # L-7
    sla_minutes = models.PositiveIntegerField(null=True, blank=True)  # L-8
    field_mapping = models.JSONField(default=dict, blank=True)  # inbound key -> lead field

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_leadsource_per_tenant")
        ]


class Lead(TenantModel):
    """L-1: unqualified inbound; never mixed into the deals pipeline."""

    class Status(models.TextChoices):
        NEW = "new"
        ATTEMPTED = "attempted"
        CONTACTED = "contacted"
        QUALIFIED = "qualified"  # set on conversion
        DISQUALIFIED = "disqualified"

    name = models.CharField(max_length=200)
    organization_name = models.CharField(max_length=255, blank=True)
    phone_raw = models.CharField(max_length=30, blank=True)
    phone_normalized = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    source = models.ForeignKey(LeadSource, null=True, blank=True, on_delete=models.SET_NULL)
    utm = models.JSONField(default=dict, blank=True)  # L-2: UTM capture
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="leads",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    note = models.TextField(blank=True)
    # L-4: disqualification requires a reason (shared configurable list with deals)
    disqualify_reason = models.ForeignKey(
        LostReason, null=True, blank=True, on_delete=models.PROTECT
    )
    # L-3: conversion lineage for source-to-revenue attribution
    converted_person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    converted_organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    converted_deal = models.ForeignKey(
        Deal, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)  # L-8

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=["tenant", "status", "owner"]),
            models.Index(fields=["tenant", "phone_normalized"]),
            models.Index(fields=["tenant", "email"]),
        ]

    def __str__(self) -> str:
        return self.name
