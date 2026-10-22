import uuid


def filter_by(queryset, params, fields, uuid_fields=()):
    """Apply exact-match query-string filters; a malformed ID matches nothing."""
    for field in fields:
        value = params.get(field)
        if not value:
            continue
        if field in uuid_fields:
            try:
                uuid.UUID(str(value))
            except ValueError:
                return queryset.none()
        queryset = queryset.filter(**{field: value})
    return queryset
