"""Real Jira Cloud data source — NOT YET IMPLEMENTED.

This is the seam for plugging in a live Jira instance once a base URL and
API token are available. Filling in the two methods below should be the
*only* change required to move off synthetic data — metrics.py and app.py
depend solely on the JiraDataSource DataFrame contract, not on where the
data came from.

Jira Cloud auth: HTTP Basic auth with (email, api_token) — NOT a bearer
token. See https://id.atlassian.com/manage-profile/security/api-tokens to
mint a token.
"""

import pandas as pd

from .base import JiraDataSource


class JiraCloudSource(JiraDataSource):
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url
        self.email = email
        self.api_token = api_token

    def get_issues(self) -> pd.DataFrame:
        # TODO: paginated JQL search against GET {base_url}/rest/api/3/search
        # (auth=(email, api_token)). Page via `startAt`/`maxResults` until
        # `total` is exhausted. Map each result's `fields` into the
        # get_issues() column contract documented in base.py — issue_type
        # from fields.issuetype.name, priority from fields.priority.name,
        # team likely needs a custom field or project->team lookup table,
        # labels from fields.labels, components from
        # [c.name for c in fields.components], created/resolved from
        # fields.created / fields.resolutiondate, current_status from
        # fields.status.name.
        raise NotImplementedError(
            "JiraCloudSource.get_issues is a stub — implement the "
            "/rest/api/3/search integration once a real Jira instance and "
            "API token are available."
        )

    def get_changelog(self) -> pd.DataFrame:
        # TODO: either expand=changelog on the same /rest/api/3/search call
        # (paginated per Jira's changelog page limits) or, per issue,
        # GET {base_url}/rest/api/3/issue/{key}/changelog. Filter history
        # items where `field == "status"` and translate each transition
        # into (issue_key, stage, entered_at, exited_at) rows matching the
        # get_changelog() contract in base.py — entered_at is the
        # transition's `created` timestamp; exited_at is the next
        # transition's timestamp for the same issue (NaT for the current
        # stage of an open issue).
        raise NotImplementedError(
            "JiraCloudSource.get_changelog is a stub — implement the "
            "changelog integration once a real Jira instance and API token "
            "are available."
        )
