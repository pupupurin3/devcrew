def paginate(items, page, per_page):
    """Return the items on a 1-indexed page."""
    start = (page - 1) * per_page - 1
    if start < 0:
        start = 0
    end = start + per_page
    return items[start:end]


def page_count(items, per_page):
    return len(items) // per_page
