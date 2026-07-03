"""AU-1..AU-4: automation engine."""
import pytest

from crm import automation, services
from crm.automation import AutomationRule, AutomationRun
from crm.models import Activity, Notification
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def _rule(ctx, **kw):
    defaults = dict(name="R", trigger="deal.created", conditions={}, actions=[
        {"type": "create_activity", "type_name": "Call",
         "subject": "Auto call", "due_in_days": 1}])
    defaults.update(kw)
    r = AutomationRule(**defaults)
    r.save()
    return r


def _fire(ctx, capture, title="A", value=0, **kw):
    with capture(execute=True):
        return services.create_deal(user=ctx["users"]["rep1"], title=title,
                                    pipeline=ctx["pipeline"], value=value, **kw)


def test_trigger_conditions_actions_happy_path(
        ctx, django_capture_on_commit_callbacks):
    _rule(ctx, conditions={"all": [{"field": "value", "op": "gte", "value": 1000}]})
    deal = _fire(ctx, django_capture_on_commit_callbacks, title="Big", value=5000)
    auto = Activity.objects.filter(subject="Auto call", deal=deal)
    assert auto.count() == 1
    run = AutomationRun.objects.get(status="success")
    assert run.detail["results"] == ["activity 'Auto call' created"]
    # below threshold → skipped, no activity
    deal2 = _fire(ctx, django_capture_on_commit_callbacks, title="Small", value=10)
    assert not Activity.objects.filter(subject="Auto call", deal=deal2).exists()
    assert AutomationRun.objects.filter(status="skipped").count() == 1


def test_custom_field_and_any_conditions(ctx, django_capture_on_commit_callbacks):
    from crm.custom_fields import CustomFieldDef, set_custom_values

    CustomFieldDef(entity="deal", name="Venue", key="venue", field_type="text").save()
    _rule(ctx, trigger="deal.stage_changed",
          conditions={"any": [{"field": "custom.venue", "op": "contains", "value": "goa"},
                              {"field": "value", "op": "gt", "value": 999999}]},
          actions=[{"type": "notify", "title": "Hot deal"}])
    deal = _fire(ctx, django_capture_on_commit_callbacks)
    set_custom_values(deal, "deal", {"venue": "Goa Beach Resort"}, ctx["users"]["rep1"])
    with django_capture_on_commit_callbacks(execute=True):
        services.change_stage(deal, ctx["stages"][1], ctx["users"]["rep1"])
    assert Notification.objects.filter(title="Hot deal").count() == 1


def test_pipeline_scoping(ctx, t2, django_capture_on_commit_callbacks):
    from crm.models import Pipeline, Stage

    other = Pipeline(name="Other")
    other.save()
    Stage(pipeline=other, name="S", order=0).save()
    _rule(ctx, pipeline=other)  # scoped to the other pipeline
    _fire(ctx, django_capture_on_commit_callbacks)  # deal in main pipeline
    assert not Activity.objects.filter(subject="Auto call").exists()


def test_loop_protection_depth_limit(ctx, django_capture_on_commit_callbacks):
    """stage_changed → move_stage would loop forever without AU-3."""
    _rule(ctx, name="loop", trigger="deal.stage_changed",
          actions=[{"type": "move_stage", "stage_name": "Proposal"}])
    deal = _fire(ctx, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        services.change_stage(deal, ctx["stages"][1], ctx["users"]["rep1"])
    deal.refresh_from_db()
    assert deal.stage.name == "Proposal"
    # chain ran but stopped: runs recorded with increasing depth, capped < MAX_DEPTH+1
    depths = list(AutomationRun.objects.values_list("depth", flat=True))
    assert max(depths) <= automation.MAX_DEPTH
    assert len(depths) <= automation.MAX_DEPTH + 1


def test_round_robin_assigns_least_loaded(ctx, django_capture_on_commit_callbacks):
    # rep2 has fewer open deals than rep1 → round robin picks rep2
    _fire(ctx, django_capture_on_commit_callbacks, title="existing rep1 deal")
    _rule(ctx, name="rr", trigger="lead.created",
          actions=[{"type": "change_owner", "username": "round_robin"}])
    from crm.leads import Lead

    with django_capture_on_commit_callbacks(execute=True):
        from crm import events

        lead = Lead(name="RR Lead", owner=ctx["users"]["rep1"])
        lead.save()
        events.emit("lead.created", {"id": lead.pk, "name": lead.name},
                    ctx["tenant"].id)
    lead.refresh_from_db()
    assert lead.owner.username == "alpha_rep2"


def test_failed_action_logged_never_raises(ctx, django_capture_on_commit_callbacks):
    _rule(ctx, actions=[{"type": "move_stage", "stage_name": "Nonexistent"}])
    _fire(ctx, django_capture_on_commit_callbacks)  # must not raise
    run = AutomationRun.objects.get()
    assert run.status == "failed"
    assert "Nonexistent" in run.detail["errors"][0]


def test_rule_api_validation_and_admin_gate(t1, api):
    good = {"name": "N", "trigger": "deal.won",
            "actions": [{"type": "notify", "title": "x"}]}
    assert api(t1["users"]["manager"]).post("/api/v1/automations/", good,
                                            format="json").status_code == 403
    admin = api(t1["users"]["admin"])
    assert admin.post("/api/v1/automations/", good, format="json").status_code == 201
    bad_action = {**good, "actions": [{"type": "launch_rocket"}]}
    assert admin.post("/api/v1/automations/", bad_action, format="json").status_code == 400
    bad_cond = {**good, "conditions": {"all": [{"field": "value", "op": "??", "value": 1}]}}
    assert admin.post("/api/v1/automations/", bad_cond, format="json").status_code == 400
