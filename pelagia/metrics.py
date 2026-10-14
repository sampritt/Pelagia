"""Consistent numeric formatting for dive metrics and share previews."""


def format_metric(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
