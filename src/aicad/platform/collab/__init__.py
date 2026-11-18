"""Collaboration: teams, project permissions, sharing, presence, comments, branches and merge requests.

- `tables`       new tables (additive: created by `create_all`, existing tables untouched)
- `permissions`  the single place that decides what a person may do on a project (none/read/comment/edit/admin)
- `branches`     per-branch workspaces, the active-branch request context, soft edit locks, presence
- `merge`        pure 3-way merge of a part (parameters, manual features, design source)
"""
