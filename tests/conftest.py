import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Team, User
from crm.models import ActivityType, LostReason, Pipeline, Stage
from tenants.context import set_current_tenant_id, tenant_context
from tenants.models import Tenant


@pytest.fixture(autouse=True)
def _clean_tenant_context():
    token = set_current_tenant_id(None)
    yield
    from tenants.context import reset

    reset(token)


def _seed_tenant(subdomain: str) -> dict:
    tenant = Tenant.objects.create(name=subdomain.title(), subdomain=subdomain)
    with tenant_context(tenant.id):
        team = Team(name="Sales")
        team.save()
        users = {}
        for uname, role in [("admin", "admin"), ("manager", "manager"),
                            ("rep1", "member"), ("rep2", "member"), ("ro", "readonly")]:
            users[uname] = User.objects.create_user(
                username=f"{subdomain}_{uname}", password="x-test-pass-123",
                tenant=tenant, role=role, team=team,
            )
        pipeline = Pipeline(name="Main")
        pipeline.save()
        stages = []
        for order, (name, rot) in enumerate([("Qualified", 7), ("Proposal", 5), ("Won-ready", None)]):
            s = Stage(pipeline=pipeline, name=name, order=order, rot_days=rot, probability=10 * (order + 1))
            s.save()
            stages.append(s)
        reason = LostReason(label="Budget")
        reason.save()
        atype = ActivityType(name="Call")
        atype.save()
    return {"tenant": tenant, "team": team, "users": users, "pipeline": pipeline,
            "stages": stages, "lost_reason": reason, "activity_type": atype}


@pytest.fixture
def t1(db):
    return _seed_tenant("alpha")


@pytest.fixture
def t2(db):
    return _seed_tenant("beta")


@pytest.fixture
def api():
    def client_for(user: User) -> APIClient:
        token, _ = Token.objects.get_or_create(user=user)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c

    return client_for
