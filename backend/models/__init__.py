from sqlalchemy.orm import declarative_base


Base = declarative_base()


def import_models() -> None:
    from backend.domains.leads.models import lead as domain_lead  # noqa: F401
    from backend.domains.leads.models import outreach_log as domain_outreach_log  # noqa: F401
    from backend.domains.leads.models import support_log as domain_support_log  # noqa: F401
    from backend.domains.social.models import social_post, social_trend  # noqa: F401
    from backend.models import (
        outreach_approval_queue,
        session,
        sync_state,
        user,
        user_support_config,
        workflow_run,
    )  # noqa: F401
