"""Data-source interface shared by synthetic and real Jira implementations.

Everything downstream (metrics.py, insights.py, app.py) depends only on the
two DataFrame contracts below — swapping SyntheticJiraSource for a real
JiraCloudSource should never require touching those modules.
"""

from abc import ABC, abstractmethod

import pandas as pd


class JiraDataSource(ABC):
    """Contract for anything that can supply Jira issue + changelog data.

    get_issues() columns:
        issue_key        str   e.g. "PAY-1042"
        project           str   project key
        team              str
        issue_type        str   Story / Bug / Task / Epic
        priority          str   Low / Medium / High / Critical
        sprint            str
        labels            list[str]
        created           pd.Timestamp
        resolved          pd.Timestamp or NaT (open issues)
        current_status    str   last status in that issue's changelog
        reopened_count    int

    get_changelog() columns (one row per stage occupancy, not per raw event):
        issue_key   str
        stage       str   member of config.WORKFLOW_STAGES or BLOCKED_STAGE
        entered_at  pd.Timestamp
        exited_at   pd.Timestamp or NaT (still in this stage)
    """

    @abstractmethod
    def get_issues(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_changelog(self) -> pd.DataFrame:
        raise NotImplementedError
